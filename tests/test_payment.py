# -*- coding: utf-8 -*-
import json
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPayment(TransactionCase):
    """Tarification d'un service et cycle de paiement du ticket."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.location = cls.env['queue.location'].create({'name': 'Pay Site'})
        cls.paid = cls.env['queue.service'].create({
            'name': 'Payant', 'code': 'PAY', 'location_id': cls.location.id,
            'payment_required': True, 'price': 5000.0})
        cls.free = cls.env['queue.service'].create({
            'name': 'Gratuit', 'code': 'FREE', 'location_id': cls.location.id})

    def test_paid_service_ticket_is_pending(self):
        ticket = self.env['queue.ticket'].create({'service_id': self.paid.id})
        self.assertEqual(ticket.payment_state, 'pending')
        self.assertEqual(ticket.payment_amount, 5000.0)

    def test_free_service_ticket_not_required(self):
        ticket = self.env['queue.ticket'].create({'service_id': self.free.id})
        self.assertEqual(ticket.payment_state, 'not_required')

    def test_register_payment_direct_agent(self):
        """Encaissement direct par l'agent → payé (l'agent valide)."""
        ticket = self.env['queue.ticket'].create({'service_id': self.paid.id})
        ticket.action_register_payment(method='counter')
        self.assertEqual(ticket.payment_state, 'paid')
        self.assertEqual(ticket.payment_method, 'counter')
        self.assertTrue(ticket.paid_at)
        self.assertEqual(ticket.payment_validated_by, self.env.user)
        ticket.action_register_payment(method='counter')  # idempotent
        self.assertEqual(ticket.payment_state, 'paid')

    def test_submit_then_validate(self):
        """Le client déclare → à valider → l'agent valide → payé."""
        ticket = self.env['queue.ticket'].create({'service_id': self.paid.id})
        ticket._submit_payment('counter')
        self.assertEqual(ticket.payment_state, 'to_validate')
        self.assertTrue(ticket.payment_submitted_at)
        ticket.action_validate_payment()
        self.assertEqual(ticket.payment_state, 'paid')

    def test_submit_then_reject(self):
        ticket = self.env['queue.ticket'].create({'service_id': self.paid.id})
        ticket._submit_payment('wave', ref='WV123')
        self.assertEqual(ticket.payment_state, 'to_validate')
        ticket.action_reject_payment()
        self.assertEqual(ticket.payment_state, 'pending')

    def test_submit_proof_requires_attachment(self):
        import base64
        ticket = self.env['queue.ticket'].create({'service_id': self.paid.id})
        with self.assertRaises(UserError):
            ticket._submit_payment('proof')   # sans preuve
        ticket._submit_payment('proof', proof=base64.b64encode(b'img'),
                               proof_filename='recu.png')
        self.assertEqual(ticket.payment_state, 'to_validate')
        self.assertTrue(ticket.payment_proof)

    def test_validate_guard(self):
        ticket = self.env['queue.ticket'].create({'service_id': self.paid.id})
        with self.assertRaises(UserError):   # rien à valider (encore pending)
            ticket.action_validate_payment()

    def test_cannot_pay_free_ticket(self):
        ticket = self.env['queue.ticket'].create({'service_id': self.free.id})
        with self.assertRaises(UserError):
            ticket.action_register_payment()


@tagged('post_install', '-at_install')
class TestPaymentApi(HttpCase):
    """Endpoint mobile : tarif exposé + paiement (simulé)."""

    TOKEN = 'PAYTOKEN'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Customer = cls.env['queue.customer']
        cls.location = cls.env['queue.location'].create({'name': 'Pay API'})
        cls.service = cls.env['queue.service'].create({
            'name': 'Consult', 'code': 'CSL', 'location_id': cls.location.id,
            'payment_required': True, 'price': 3000.0})
        cls.customer = Customer.create({
            'email': 'pay@test.com', 'token': Customer._hash(cls.TOKEN),
            'token_expiry': fields.Datetime.now() + timedelta(days=1)})
        cls.customer._ensure_partner()

    def _call(self, endpoint, params):
        data = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                           'params': params})
        return self.url_open(endpoint, data=data,
                             headers={'Content-Type': 'application/json'}
                             ).json().get('result', {})

    def test_price_exposed_and_payment_flow(self):
        site = self._call('/api/queue/site', {'qr_token': self.location.qr_token})
        svc = site['services'][0]
        self.assertTrue(svc['payment_required'])
        self.assertEqual(svc['price'], 3000.0)
        res = self._call('/api/queue/ticket/create', {
            'auth_token': self.TOKEN, 'service_id': self.service.id,
            'qr_token': self.location.qr_token})
        self.assertEqual(res['ticket']['payment_state'], 'pending')
        self.assertEqual(res['ticket']['payment_amount'], 3000.0)
        # Sans méthode Wave directe configurée → à valider (Wave marchand).
        pay = self._call('/api/queue/ticket/pay', {
            'auth_token': self.TOKEN, 'ticket_id': res['ticket']['id'],
            'method': 'counter'})
        self.assertEqual(pay['ticket']['payment_state'], 'to_validate')

    def test_wave_webhook_marks_paid(self):
        import json
        # Un ticket dont la référence Wave est connue.
        ticket = self.env['queue.ticket'].create({
            'service_id': self.service.id, 'partner_id': self.customer.partner_id.id})
        ticket.write({'payment_state': 'to_validate', 'payment_ref': 'SESS-1'})
        self.env['ir.config_parameter'].sudo().set_param(
            'queue_management.wave_webhook_secret', 'topsecret')
        body = json.dumps({'type': 'checkout.session.completed',
                           'data': {'id': 'SESS-1', 'payment_status': 'succeeded'}})
        import hashlib, hmac
        sig = hmac.new(b'topsecret', body.encode(), hashlib.sha256).hexdigest()
        resp = self.url_open('/api/queue/wave/webhook', data=body.encode(),
                             headers={'Content-Type': 'application/json',
                                      'Wave-Signature': sig})
        self.assertEqual(resp.status_code, 200)
        ticket.invalidate_recordset(['payment_state'])
        self.assertEqual(ticket.payment_state, 'paid')

    def test_wave_webhook_rejects_bad_signature(self):
        import json
        self.env['ir.config_parameter'].sudo().set_param(
            'queue_management.wave_webhook_secret', 'topsecret')
        body = json.dumps({'data': {'id': 'X', 'payment_status': 'succeeded'}})
        resp = self.url_open('/api/queue/wave/webhook', data=body.encode(),
                             headers={'Content-Type': 'application/json',
                                      'Wave-Signature': 'wrong'})
        self.assertEqual(resp.status_code, 403)


@tagged('post_install', '-at_install')
class TestSectorTemplates(TransactionCase):
    """Secteurs, modèles et création de services depuis un modèle."""

    def test_catalog_loaded(self):
        health = self.env.ref('queue_management.sector_health')
        self.assertTrue(health.template_ids)
        transport = self.env.ref('queue_management.sector_transport')
        billet = transport.template_ids.filtered(lambda t: t.code == 'BIL')
        self.assertTrue(billet.payment_required)

    def test_setup_wizard_prefills_from_sector(self):
        wizard = self.env['queue.setup.wizard'].new({
            'company_name': 'Test Santé',
            'sector_id': self.env.ref('queue_management.sector_health').id})
        wizard._onchange_sector_id()
        self.assertTrue(wizard.line_ids)
        self.assertIn('CG', wizard.line_ids.mapped('code'))

    def test_from_template_wizard_creates_services(self):
        location = self.env['queue.location'].create({'name': 'Tmpl Site'})
        sector = self.env.ref('queue_management.sector_transport')
        wizard = self.env['queue.service.from.template.wizard'].create({
            'location_id': location.id, 'sector_id': sector.id,
            'template_ids': [(6, 0, sector.template_ids.ids)]})
        wizard.action_add()
        codes = location.service_ids.mapped('code')
        self.assertIn('BIL', codes)
        billet = location.service_ids.filtered(lambda s: s.code == 'BIL')
        self.assertTrue(billet.payment_required)
        # Ré-exécuter n'ajoute pas de doublon (préfixe déjà pris).
        wizard2 = self.env['queue.service.from.template.wizard'].create({
            'location_id': location.id, 'sector_id': sector.id,
            'template_ids': [(6, 0, sector.template_ids.ids)]})
        wizard2.action_add()
        self.assertEqual(len(location.service_ids), len(sector.template_ids))
