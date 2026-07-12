# -*- coding: utf-8 -*-
import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, HttpCase, tagged


@tagged('post_install', '-at_install')
class TestQueueCustomerOtp(TransactionCase):
    """Logique d'authentification email/OTP, sans passer par le HTTP."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['queue.customer'].create({'email': 'OTP@Test.com'})

    def test_email_normalized_and_partner_deferred(self):
        self.assertEqual(self.customer.email, 'otp@test.com')
        # Le partenaire miroir n'est PAS créé à la demande de code : un flood
        # d'emails ne doit pas polluer l'annuaire res.partner.
        self.assertFalse(self.customer.partner_id)

    def test_email_normalized_on_write(self):
        self.customer.write({'email': 'Fixed.Case@Test.com'})
        self.assertEqual(self.customer.email, 'fixed.case@test.com')

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
        # Seul le hash du jeton est stocké, avec une expiration.
        self.assertEqual(self.customer.token, self.customer._hash(token))
        self.assertNotEqual(self.customer.token, token)
        self.assertTrue(self.customer.token_expiry)
        # Le partenaire miroir est créé à la première connexion réussie.
        self.assertTrue(self.customer.partner_id)
        self.assertEqual(self.customer.partner_id.email, 'otp@test.com')
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

    def test_send_otp_smtp_failure_rearms(self):
        """Échec SMTP → exception propagée + anti-spam réarmé (retry possible)."""
        Customer = type(self.env['queue.customer'])
        with patch.object(Customer, '_send_otp_email', side_effect=RuntimeError('smtp down')):
            with self.assertRaises(RuntimeError):
                self.customer.send_otp()
        self.assertFalse(self.customer.last_otp_sent)
        self.assertFalse(self.customer.otp_hash)

    def test_revoke_session(self):
        self._arm_otp('123456')
        self.customer.verify_otp('123456')
        self.customer.sudo().fcm_token = 'device-abc'
        self.customer._revoke_session()
        self.assertFalse(self.customer.token)
        self.assertFalse(self.customer.token_expiry)
        self.assertFalse(self.customer.sudo().fcm_token)

    def test_register_fcm_steals_token_from_previous_account(self):
        """Un jeton FCM (= un appareil) ne doit appartenir qu'à UN client."""
        other = self.env['queue.customer'].create({'email': 'ancien@test.com'})
        other._register_fcm('device-shared')
        self.customer._register_fcm('device-shared')
        self.assertFalse(other.sudo().fcm_token)
        self.assertEqual(self.customer.sudo().fcm_token, 'device-shared')

    def test_cron_purges_only_unverified(self):
        Customer = self.env['queue.customer']
        old = fields.Datetime.now() - timedelta(days=40)
        ghost = Customer.create({'email': 'ghost@test.com'})
        verified = Customer.create({'email': 'reel@test.com'})
        verified.write({
            'otp_hash': verified._hash('123456'),
            'otp_expiry': fields.Datetime.now() + timedelta(minutes=5),
        })
        verified.verify_otp('123456')
        self.env.cr.execute(
            "UPDATE queue_customer SET create_date=%s WHERE id IN %s",
            (old, tuple((ghost | verified).ids)))
        (ghost | verified).invalidate_recordset()
        Customer._cron_purge_unverified()
        self.assertFalse(ghost.exists())
        self.assertTrue(verified.exists())


@tagged('post_install', '-at_install')
class TestQueueRateLimit(TransactionCase):
    """Compteurs PG du rate-limit (logique pure, sans HTTP)."""

    def test_blocks_after_max_then_reports_retry(self):
        Bucket = self.env['queue.rate.limit']
        for _ in range(5):
            limited, _retry = Bucket.check_and_record('t:1.2.3.4', 5, 60, 300)
            self.assertFalse(limited)
        limited, retry = Bucket.check_and_record('t:1.2.3.4', 5, 60, 300)
        self.assertTrue(limited)
        self.assertEqual(retry, 300)
        # Une autre clé (autre IP) n'est pas affectée.
        limited, _retry = Bucket.check_and_record('t:5.6.7.8', 5, 60, 300)
        self.assertFalse(limited)

    def test_reset_key_unblocks(self):
        Bucket = self.env['queue.rate.limit']
        for _ in range(6):
            Bucket.check_and_record('t:reset', 5, 60, 300)
        Bucket.reset_key('t:reset')
        limited, _retry = Bucket.check_and_record('t:reset', 5, 60, 300)
        self.assertFalse(limited)


@tagged('post_install', '-at_install')
class TestQueueApi(HttpCase):
    """Parcours mobile complet via les endpoints JSON-RPC."""

    TOKEN = 'TESTTOKEN123'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Customer = cls.env['queue.customer']
        cls.location = cls.env['queue.location'].create({'name': "API Site"})
        cls.service = cls.env['queue.service'].create({
            'name': "Guichet API", 'code': 'API', 'location_id': cls.location.id,
        })
        # La base ne stocke que le hash du jeton de session.
        cls.customer = Customer.create({
            'email': 'client@test.com',
            'token': Customer._hash(cls.TOKEN),
            'token_expiry': fields.Datetime.now() + timedelta(days=1),
        })
        cls.customer._ensure_partner()

    def setUp(self):
        super().setUp()
        # Les buckets de rate-limit persistent entre tests (même cursor) :
        # on repart de zéro pour l'IP de test.
        for scope in ('queue_otp_req', 'queue_otp_verif'):
            self.env['queue.rate.limit'].reset_key(f'{scope}:127.0.0.1')

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
        # Écho du jeton : l'app le garde pour la prise de ticket.
        self.assertEqual(res['site']['qr_token'], self.location.qr_token)
        self.assertEqual(len(res['services']), 1)
        self.assertEqual(res['services'][0]['code'], 'API')

    def test_site_bad_qr(self):
        res = self._call('/api/queue/site', {'qr_token': 'nope'})
        self.assertEqual(res['status'], 'error')

    def _create_ticket(self, service, token=None):
        return self._call('/api/queue/ticket/create', {
            'auth_token': token or self.TOKEN,
            'service_id': service.id,
            'qr_token': service.location_id.qr_token,
        })

    def test_ticket_lifecycle(self):
        # Création
        res = self._create_ticket(self.service)
        self.assertEqual(res['status'], 'ok')
        ticket_id = res['ticket']['id']
        self.assertEqual(res['ticket']['state'], 'waiting')
        self.assertEqual(res['ticket']['position'], 1)
        # Doublon → renvoie le même ticket
        res2 = self._create_ticket(self.service)
        self.assertEqual(res2['ticket']['id'], ticket_id)
        # Statut
        res3 = self._call('/api/queue/ticket/status', {
            'auth_token': self.TOKEN, 'ticket_id': ticket_id})
        self.assertEqual(res3['ticket']['state'], 'waiting')
        # Annulation
        res4 = self._call('/api/queue/ticket/cancel', {
            'auth_token': self.TOKEN, 'ticket_id': ticket_id})
        self.assertEqual(res4['ticket']['state'], 'cancelled')

    def test_requires_auth(self):
        res = self._call('/api/queue/ticket/create', {
            'service_id': self.service.id,
            'qr_token': self.location.qr_token})
        self.assertEqual(res['status'], 'error')
        # Code machine-lisible : l'app déclenche sa déconnexion dessus.
        self.assertEqual(res.get('code'), 'auth_required')

    def test_ticket_create_requires_site_qr(self):
        """Le service_id seul (énumérable) ne suffit pas : preuve de présence."""
        res = self._call('/api/queue/ticket/create', {
            'auth_token': self.TOKEN, 'service_id': self.service.id})
        self.assertEqual(res['status'], 'error')
        res2 = self._call('/api/queue/ticket/create', {
            'auth_token': self.TOKEN, 'service_id': self.service.id,
            'qr_token': 'faux-jeton'})
        self.assertEqual(res2['status'], 'error')

    def test_remote_ticket_flow(self):
        """Ticket à distance : refusé si la file ne l'autorise pas, canal
        « remote » sinon (le qr_token mémorisé reste exigé)."""
        # Par défaut la file refuse le distant.
        res = self._call('/api/queue/ticket/create', {
            'auth_token': self.TOKEN, 'service_id': self.service.id,
            'qr_token': self.location.qr_token, 'remote': True})
        self.assertEqual(res['status'], 'error')
        self.assertIn('distance', res['message'])
        # File ouverte au distant → ticket créé avec le bon canal.
        self.service.write({'remote_enabled': True})
        res2 = self._call('/api/queue/ticket/create', {
            'auth_token': self.TOKEN, 'service_id': self.service.id,
            'qr_token': self.location.qr_token, 'remote': True})
        self.assertEqual(res2['status'], 'ok')
        self.assertEqual(res2['ticket']['channel'], 'remote')
        # Sans qr_token, même à distance : refus (anti-énumération).
        res3 = self._call('/api/queue/ticket/create', {
            'auth_token': self.TOKEN, 'service_id': self.service.id,
            'remote': True})
        self.assertEqual(res3['status'], 'error')
        # Le drapeau est exposé par la découverte de site.
        site = self._call('/api/queue/site', {'qr_token': self.location.qr_token})
        self.assertTrue(site['services'][0]['remote'])
        # Nettoyage pour les autres tests.
        self._call('/api/queue/ticket/cancel', {
            'auth_token': self.TOKEN, 'ticket_id': res2['ticket']['id']})
        self.service.write({'remote_enabled': False})

    def test_active_tickets_quota(self):
        """Plafond global de tickets actifs par client (anti-flood)."""
        from odoo.addons.queue_management.controllers import mobile_api
        service2 = self.env['queue.service'].create({
            'name': "File 2", 'code': 'AP2', 'location_id': self.location.id})
        with patch.object(mobile_api, '_MAX_ACTIVE_TICKETS', 1):
            r1 = self._create_ticket(self.service)
            self.assertEqual(r1['status'], 'ok')
            r2 = self._create_ticket(service2)
            self.assertEqual(r2['status'], 'error')
            self.assertIn('trop de tickets', r2['message'])
        # Nettoyage : on annule le ticket pris pour ne pas gêner les autres tests.
        self._call('/api/queue/ticket/cancel', {
            'auth_token': self.TOKEN, 'ticket_id': r1['ticket']['id']})

    def test_expired_session_rejected(self):
        self.customer.write({
            'token_expiry': fields.Datetime.now() - timedelta(minutes=1)})
        res = self._call('/api/queue/tickets', {'auth_token': self.TOKEN})
        self.assertEqual(res['status'], 'error')
        self.customer.write({
            'token_expiry': fields.Datetime.now() + timedelta(days=1)})

    def test_logout_revokes_session_and_fcm(self):
        self.customer.write({'fcm_token': 'device-1'})
        res = self._call('/api/queue/auth/logout', {'auth_token': self.TOKEN})
        self.assertEqual(res['status'], 'ok')
        self.assertFalse(self.customer.token)
        self.assertFalse(self.customer.fcm_token)
        # Le jeton révoqué ne passe plus.
        res2 = self._call('/api/queue/tickets', {'auth_token': self.TOKEN})
        self.assertEqual(res2['status'], 'error')
        # On réarme la session pour les autres tests de la classe.
        self.customer.write({
            'token': self.env['queue.customer']._hash(self.TOKEN),
            'token_expiry': fields.Datetime.now() + timedelta(days=1),
        })

    def test_request_otp_rejects_invalid_email(self):
        res = self._call('/api/queue/auth/request_otp', {'email': 'pas-un-email'})
        self.assertEqual(res['status'], 'error')
        # Header injection : refusée par email_normalize.
        res2 = self._call('/api/queue/auth/request_otp',
                          {'email': 'a@b.com\nBcc: spam@evil.com'})
        self.assertEqual(res2['status'], 'error')

    def test_request_otp_rate_limited_by_ip(self):
        # Force une limite basse pour ne pas faire 30 requêtes HTTP.
        from odoo.addons.queue_management.controllers import mobile_api
        with patch.dict(mobile_api._RL_OTP_REQUEST,
                        {'max_requests': 2, 'window_seconds': 3600,
                         'block_seconds': 600}):
            r1 = self._call('/api/queue/auth/request_otp', {'email': 'rl1@test.com'})
            self.assertEqual(r1['status'], 'ok')
            r2 = self._call('/api/queue/auth/request_otp', {'email': 'rl2@test.com'})
            self.assertEqual(r2['status'], 'ok')
            r3 = self._call('/api/queue/auth/request_otp', {'email': 'rl3@test.com'})
            self.assertEqual(r3['status'], 'error')
            self.assertIn('Trop de tentatives', r3['message'])
        # Aucun res.partner créé par les demandes d'OTP (création différée).
        self.assertFalse(self.env['res.partner'].search(
            [('email', 'in', ['rl1@test.com', 'rl2@test.com'])]))

    def _enable_appointments(self):
        self.service.write({
            'appointment_enabled': True, 'slot_duration': 30, 'slot_capacity': 1})
        for d in range(7):
            self.env['queue.opening.hour'].create({
                'service_id': self.service.id, 'dayofweek': str(d),
                'hour_from': 8.0, 'hour_to': 9.0})

    def test_appointment_booking_api(self):
        from datetime import date, timedelta as td
        self._enable_appointments()
        day = (date.today() + td(days=1)).strftime('%Y-%m-%d')
        slots = self._call('/api/queue/slots',
                           {'service_id': self.service.id, 'date': day})
        self.assertEqual(slots['status'], 'ok')
        self.assertTrue(slots['slots'])
        slot = slots['slots'][0]['time']
        book = self._call('/api/queue/appointment/book', {
            'auth_token': self.TOKEN, 'service_id': self.service.id,
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
            'auth_token': self.TOKEN, 'ticket_id': ticket.id})
        self.assertEqual(res['status'], 'ok')
        self.assertEqual(res['ticket']['state'], 'waiting')

    def test_cannot_touch_others_ticket(self):
        Customer = self.env['queue.customer']
        other = Customer.create({
            'email': 'intrus@test.com', 'token': Customer._hash('INTRUS'),
            'token_expiry': fields.Datetime.now() + timedelta(days=1)})
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

    def test_public_pages_have_security_headers(self):
        """Pages publiques (borne + affichage) : CSP stricte + nosniff."""
        for path in ('/queue/kiosk/%s' % self.location.qr_token,
                     '/queue/display/%s' % self.location.qr_token,
                     '/queue/display/%s/data' % self.location.qr_token):
            resp = self.url_open(path)
            self.assertEqual(resp.status_code, 200, path)
            csp = resp.headers.get('Content-Security-Policy', '')
            self.assertIn("default-src 'none'", csp, path)
            self.assertIn("frame-ancestors 'none'", csp, path)
            self.assertEqual(resp.headers.get('X-Content-Type-Options'),
                             'nosniff', path)

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

    def test_kiosk_ticket_rate_limited(self):
        """La borne encaisse un rythme humain mais bloque l'inondation."""
        from odoo.addons.queue_management.controllers import kiosk as kiosk_ctl
        self.env['queue.rate.limit'].reset_key('queue_kiosk:127.0.0.1')
        with patch.dict(kiosk_ctl._RL_KIOSK_TICKET,
                        {'max_requests': 2, 'window_seconds': 60,
                         'block_seconds': 60}):
            for _ in range(2):
                resp = self.url_open(
                    '/queue/kiosk/%s/ticket' % self.location.qr_token,
                    data={'service_id': self.service.id})
                self.assertEqual(resp.json()['status'], 'ok')
            resp = self.url_open(
                '/queue/kiosk/%s/ticket' % self.location.qr_token,
                data={'service_id': self.service.id})
            self.assertEqual(resp.json()['status'], 'error')
        self.env['queue.rate.limit'].reset_key('queue_kiosk:127.0.0.1')

    def test_kiosk_bad_token_404(self):
        self.assertEqual(self.url_open('/queue/kiosk/nope').status_code, 404)
