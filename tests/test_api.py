# -*- coding: utf-8 -*-
import json
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, HttpCase, tagged


@tagged('post_install', '-at_install')
class TestQueueCustomerOtp(TransactionCase):
    """Logique d'authentification email/OTP, sans passer par le HTTP."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['queue.customer'].create({'email': 'OTP@Test.com'})

    def test_email_normalized_and_partner_created(self):
        self.assertEqual(self.customer.email, 'otp@test.com')
        self.assertTrue(self.customer.partner_id)
        self.assertEqual(self.customer.partner_id.email, 'otp@test.com')

    def _arm_otp(self, code='123456', minutes=10):
        self.customer.write({
            'otp_hash': self.customer._hash(code),
            'otp_expiry': fields.Datetime.now() + timedelta(minutes=minutes),
            'otp_attempts': 0,
        })

    def test_verify_wrong_then_right(self):
        self._arm_otp('123456')
        self.assertFalse(self.customer.verify_otp('000000'))
        self.assertEqual(self.customer.otp_attempts, 1)
        token = self.customer.verify_otp('123456')
        self.assertTrue(token)
        self.assertEqual(self.customer.token, token)
        # OTP consommé : non rejouable.
        self.assertFalse(self.customer.verify_otp('123456'))

    def test_expired_otp_rejected(self):
        self._arm_otp('123456', minutes=-1)
        self.assertFalse(self.customer.verify_otp('123456'))

    def test_attempts_lockout(self):
        self._arm_otp('123456')
        for _ in range(self.customer.OTP_MAX_ATTEMPTS):
            self.customer.verify_otp('000000')
        # Même le bon code échoue une fois le quota dépassé.
        self.assertFalse(self.customer.verify_otp('123456'))


@tagged('post_install', '-at_install')
class TestQueueApi(HttpCase):
    """Parcours mobile complet via les endpoints JSON-RPC."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.location = cls.env['queue.location'].create({'name': "API Site"})
        cls.service = cls.env['queue.service'].create({
            'name': "Guichet API", 'code': 'API', 'location_id': cls.location.id,
        })
        cls.customer = cls.env['queue.customer'].create({
            'email': 'client@test.com', 'token': 'TESTTOKEN123',
        })

    def _call(self, endpoint, params=None):
        data = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                           'params': params or {}})
        resp = self.url_open(endpoint, data=data,
                             headers={'Content-Type': 'application/json'})
        return resp.json().get('result', {})

    def test_site_discovery_by_qr(self):
        res = self._call('/api/queue/site', {'qr_token': self.location.qr_token})
        self.assertEqual(res['status'], 'ok')
        self.assertEqual(res['site']['name'], "API Site")
        self.assertEqual(len(res['services']), 1)
        self.assertEqual(res['services'][0]['code'], 'API')

    def test_site_bad_qr(self):
        res = self._call('/api/queue/site', {'qr_token': 'nope'})
        self.assertEqual(res['status'], 'error')

    def test_ticket_lifecycle(self):
        # Création
        res = self._call('/api/queue/ticket/create', {
            'auth_token': 'TESTTOKEN123', 'service_id': self.service.id})
        self.assertEqual(res['status'], 'ok')
        ticket_id = res['ticket']['id']
        self.assertEqual(res['ticket']['state'], 'waiting')
        self.assertEqual(res['ticket']['position'], 1)
        # Doublon → renvoie le même ticket
        res2 = self._call('/api/queue/ticket/create', {
            'auth_token': 'TESTTOKEN123', 'service_id': self.service.id})
        self.assertEqual(res2['ticket']['id'], ticket_id)
        # Statut
        res3 = self._call('/api/queue/ticket/status', {
            'auth_token': 'TESTTOKEN123', 'ticket_id': ticket_id})
        self.assertEqual(res3['ticket']['state'], 'waiting')
        # Annulation
        res4 = self._call('/api/queue/ticket/cancel', {
            'auth_token': 'TESTTOKEN123', 'ticket_id': ticket_id})
        self.assertEqual(res4['ticket']['state'], 'cancelled')

    def test_requires_auth(self):
        res = self._call('/api/queue/ticket/create', {'service_id': self.service.id})
        self.assertEqual(res['status'], 'error')

    def _enable_appointments(self):
        self.service.write({
            'appointment_enabled': True, 'slot_duration': 30, 'slot_capacity': 1})
        for d in range(7):
            self.env['queue.opening.hour'].create({
                'service_id': self.service.id, 'dayofweek': str(d),
                'hour_from': 8.0, 'hour_to': 9.0})

    def test_appointment_booking_api(self):
        from datetime import date, timedelta
        self._enable_appointments()
        day = (date.today() + timedelta(days=1)).strftime('%Y-%m-%d')
        slots = self._call('/api/queue/slots',
                           {'service_id': self.service.id, 'date': day})
        self.assertEqual(slots['status'], 'ok')
        self.assertTrue(slots['slots'])
        slot = slots['slots'][0]['time']
        book = self._call('/api/queue/appointment/book', {
            'auth_token': 'TESTTOKEN123', 'service_id': self.service.id,
            'slot': slot})
        self.assertEqual(book['status'], 'ok')
        self.assertEqual(book['ticket']['state'], 'scheduled')
        # Le même créneau (capacité 1) n'est plus disponible.
        slots2 = self._call('/api/queue/slots',
                            {'service_id': self.service.id, 'date': day})
        self.assertEqual(slots2['slots'][0]['available'], 0)

    def test_appointment_checkin_api(self):
        ticket = self.env['queue.ticket'].create({
            'service_id': self.service.id,
            'partner_id': self.customer.partner_id.id,
            'channel': 'appointment', 'state': 'scheduled',
            'scheduled_time': fields.Datetime.now()})
        res = self._call('/api/queue/ticket/checkin', {
            'auth_token': 'TESTTOKEN123', 'ticket_id': ticket.id})
        self.assertEqual(res['status'], 'ok')
        self.assertEqual(res['ticket']['state'], 'waiting')

    def test_cannot_touch_others_ticket(self):
        other = self.env['queue.customer'].create({
            'email': 'intrus@test.com', 'token': 'INTRUS'})
        ticket = self.env['queue.ticket'].create({
            'service_id': self.service.id,
            'partner_id': self.customer.partner_id.id})
        res = self._call('/api/queue/ticket/status', {
            'auth_token': 'INTRUS', 'ticket_id': ticket.id})
        self.assertEqual(res['status'], 'error')


@tagged('post_install', '-at_install')
class TestQueueKiosk(HttpCase):
    """Borne tactile : page publique + création de ticket anonyme."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.location = cls.env['queue.location'].create({'name': "Borne Site"})
        cls.service = cls.env['queue.service'].create({
            'name': "Borne Svc", 'code': 'KSK', 'location_id': cls.location.id,
        })

    def test_kiosk_page_renders(self):
        resp = self.url_open('/queue/kiosk/%s' % self.location.qr_token)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Borne Site", resp.text)
        self.assertIn("Borne Svc", resp.text)

    def test_kiosk_creates_anonymous_ticket(self):
        resp = self.url_open(
            '/queue/kiosk/%s/ticket' % self.location.qr_token,
            data={'service_id': self.service.id})
        body = resp.json()
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['ticket']['service'], "Borne Svc")
        ticket = self.env['queue.ticket'].search(
            [('name', '=', body['ticket']['name'])], limit=1)
        self.assertEqual(ticket.channel, 'kiosk')
        self.assertFalse(ticket.partner_id)

    def test_kiosk_rejects_foreign_service(self):
        resp = self.url_open(
            '/queue/kiosk/%s/ticket' % self.location.qr_token,
            data={'service_id': 999999})
        self.assertEqual(resp.json()['status'], 'error')

    def test_kiosk_bad_token_404(self):
        self.assertEqual(self.url_open('/queue/kiosk/nope').status_code, 404)
