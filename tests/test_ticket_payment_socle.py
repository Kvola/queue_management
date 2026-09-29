# -*- coding: utf-8 -*-
"""Le paiement d'un ticket passe par le socle ``queue.payment``.

Le ticket garde son vocabulaire (en attente / à valider / payé), celui que
lisent l'app, la console et le portail ; l'argent, lui, n'existe que dans le
socle, et le ticket n'est écrit que par les crochets du socle.
"""
import base64

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

_PNG = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'\x00' * 32)


@tagged('post_install', '-at_install')
class TestTicketPaymentSocle(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.location = cls.env['queue.location'].create({'name': 'Socle'})
        cls.service = cls.env['queue.service'].create({
            'name': 'Radio', 'code': 'RAD', 'location_id': cls.location.id,
            'payment_required': True, 'price': 5000.0})
        cls.agent = new_test_user(
            cls.env, login='caisse_socle',
            groups='base.group_user,queue_management.group_queue_agent')
        cls.manager = new_test_user(
            cls.env, login='resp_socle',
            groups='base.group_user,queue_management.group_queue_manager')

    def _ticket(self):
        return self.env['queue.ticket'].create({'service_id': self.service.id})

    def test_a_declaration_creates_a_payment_to_validate(self):
        ticket = self._ticket()
        ticket._submit_payment('proof', ref='WV-9', proof=_PNG,
                               proof_filename='recu.png')
        payment = ticket.sudo().payment_id
        self.assertEqual(ticket.payment_state, 'to_validate')
        self.assertEqual(payment.state, 'to_validate')
        self.assertEqual((payment.res_model, payment.res_id),
                         ('queue.ticket', ticket.id))
        self.assertEqual(payment.amount, 5000.0)
        self.assertEqual(payment.provider_ref, 'WV-9')
        # La preuve vit sur le paiement, le ticket la montre.
        self.assertTrue(payment.proof)
        self.assertTrue(ticket.payment_proof)

    def test_the_agent_validates_and_is_the_signatory(self):
        ticket = self._ticket()
        ticket._submit_payment('counter')
        ticket.with_user(self.agent).action_validate_payment()
        payment = ticket.sudo().payment_id
        self.assertEqual(payment.state, 'paid')
        self.assertEqual(payment.validated_by, self.agent)
        self.assertEqual(ticket.payment_state, 'paid')
        self.assertEqual(ticket.payment_validated_by, self.agent)

    def test_the_agent_reads_the_ticket_without_access_errors(self):
        """Les champs du socle (paiement, remboursements) ne doivent pas
        faire lever l'ouverture d'un ticket par un agent."""
        ticket = self._ticket()
        ticket._submit_payment('proof', proof=_PNG)
        data = ticket.with_user(self.agent)._console_payment(with_ticket=True)
        self.assertTrue(data['has_proof'])
        ticket.with_user(self.agent).read(['payment_state', 'payment_proof'])

    def test_a_rejection_keeps_the_proof_in_the_file_not_on_the_ticket(self):
        ticket = self._ticket()
        ticket._submit_payment('proof', proof=_PNG)
        rejected = ticket.sudo().payment_id
        ticket.with_user(self.agent).action_reject_payment()
        self.assertEqual(ticket.payment_state, 'pending')
        self.assertEqual(rejected.state, 'failed')
        self.assertTrue(rejected.proof, "la pièce reste au dossier")
        self.assertFalse(ticket.payment_proof)
        # Le client redéclare : un NOUVEAU paiement, jamais le rejeté.
        ticket._submit_payment('counter')
        self.assertNotEqual(ticket.sudo().payment_id, rejected)

    def test_direct_collection_at_the_counter(self):
        ticket = self._ticket()
        ticket.with_user(self.agent).action_register_payment('cash')
        payment = ticket.sudo().payment_id
        self.assertEqual((payment.state, payment.method), ('paid', 'cash'))
        self.assertEqual(ticket.payment_state, 'paid')

    def test_validating_twice_credits_once(self):
        ticket = self._ticket()
        ticket._submit_payment('counter')
        ticket.action_validate_payment()
        with self.assertRaises(UserError):
            ticket.action_validate_payment()
        paid = self.env['queue.payment'].sudo().search([
            ('res_model', '=', 'queue.ticket'), ('res_id', '=', ticket.id),
            ('state', '=', 'paid')])
        self.assertEqual(len(paid), 1)

    def test_a_reverted_validation_reopens_the_ticket(self):
        ticket = self._ticket()
        ticket.action_register_payment()
        ticket.sudo().payment_id.action_revert(reason="preuve falsifiée")
        self.assertEqual(ticket.payment_state, 'pending')

    def test_refund_through_the_socle(self):
        ticket = self._ticket()
        ticket.action_register_payment()
        wizard = self.env['queue.ticket.refund.wizard'].with_user(
            self.manager).create({'ticket_id': ticket.id,
                                  'reason': "Examen non réalisé"})
        self.assertEqual(wizard.amount, 5000.0)
        wizard.action_refund()
        refund = ticket.sudo().refund_ids
        self.assertEqual(refund.amount, 5000.0)
        self.assertEqual(ticket.payment_state, 'refunded')

    def test_one_cannot_refund_more_than_was_paid(self):
        ticket = self._ticket()
        ticket.action_register_payment()
        # ValidationError hérite de UserError ; assertRaises d'Odoo refuse un tuple.
        with self.assertRaises(UserError):
            ticket.sudo()._create_refund(6000.0, reason="trop")

    def test_the_provider_fee_follows_the_company_settings(self):
        config = self.env['queue.payment.method.config'].sudo().search([
            ('company_id', '=', self.env.company.id), ('method', '=', 'wave')],
            limit=1)
        if not config:
            self.skipTest("Pas de réglage Wave pour cette société.")
        config.write({'fee_percent': 1.0, 'fee_mode': 'optional'})
        ticket = self._ticket()
        ticket._submit_payment('wave')
        self.assertEqual(ticket.sudo().payment_id.fee_amount, 50.0)
