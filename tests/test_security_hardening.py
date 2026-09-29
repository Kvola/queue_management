# -*- coding: utf-8 -*-
"""Durcissement des portes publiques (audit du 2026-09-29).

Chaque test nomme l'abus qu'il empêche : limite d'appels contournée par un
en-tête choisi par le client, webhook Wave qui ressuscite un ticket annulé ou
solde un montant partiel, preuve de paiement quelconque, identifiant
illisible qui faisait une erreur 500, encaissement direct sur la clé de la
plateforme au lieu de celle de l'établissement.
"""
import base64
import hashlib
import hmac
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.queue_management.controllers import net

_PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64


@tagged('post_install', '-at_install')
class TestClientIp(TransactionCase):
    """L'adresse servant de clé de limite ne se choisit pas par en-tête."""

    def _ip(self, remote_addr, forwarded=''):
        fake = SimpleNamespace(httprequest=SimpleNamespace(
            remote_addr=remote_addr,
            headers={'X-Forwarded-For': forwarded} if forwarded else {}))
        with patch.object(net, 'request', fake):
            return net.client_ip()

    def test_public_peer_ignores_the_header(self):
        # Client joignant Odoo en direct : l'en-tête est sa parole, pas un fait.
        self.assertEqual(self._ip('41.202.1.1', '1.2.3.4'), '41.202.1.1')

    def test_behind_our_proxy_the_last_hop_counts(self):
        # Le proxy ajoute l'adresse qu'il voit EN DERNIER ; ce qui précède
        # vient du client et peut être inventé.
        self.assertEqual(
            self._ip('172.18.0.1', '6.6.6.6, 41.202.1.1'), '41.202.1.1')
        self.assertEqual(self._ip('127.0.0.1', '41.202.1.1'), '41.202.1.1')

    def test_no_header_falls_back_to_the_peer(self):
        self.assertEqual(self._ip('127.0.0.1'), '127.0.0.1')
        self.assertEqual(self._ip(None), 'unknown')


@tagged('post_install', '-at_install')
class TestPublicDoorsHardening(HttpCase):

    TOKEN = 'HARDEN-TOKEN'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Clinique Durcie'})
        cls.location = cls.env['queue.location'].create({
            'name': 'Site durci', 'company_id': cls.company.id})
        cls.service = cls.env['queue.service'].create({
            'name': 'Consultation', 'code': 'CD', 'location_id': cls.location.id,
            'payment_required': True, 'price': 5000.0})
        Customer = cls.env['queue.customer']
        cls.customer = Customer.create({
            'email': 'durci@test.com', 'token': Customer._hash(cls.TOKEN),
            'token_expiry': fields.Datetime.now() + timedelta(days=1)})
        cls.customer._ensure_partner()
        cls.env['ir.config_parameter'].sudo().set_param(
            'queue_management.wave_webhook_secret', 'hook-secret')

    def _call(self, endpoint, params):
        data = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                           'params': params})
        return self.url_open(endpoint, data=data,
                             headers={'Content-Type': 'application/json'}
                             ).json().get('result', {})

    def _ticket(self, **vals):
        return self.env['queue.ticket'].create(dict({
            'service_id': self.service.id,
            'partner_id': self.customer.partner_id.id}, **vals))

    def _webhook(self, payload, path='/api/queue/wave/webhook'):
        body = json.dumps(payload).encode()
        sig = hmac.new(b'hook-secret', body, hashlib.sha256).hexdigest()
        return self.url_open(path, data=body, headers={
            'Content-Type': 'application/json', 'Wave-Signature': sig})

    # --- Limite d'appels -------------------------------------------------

    def test_rotating_forwarded_for_does_not_evade_the_kiosk_limit(self):
        """12 tickets/min par borne : changer le premier élément de
        l'en-tête ne remet plus le compteur à zéro."""
        url = '/queue/kiosk/%s/ticket' % self.location.kiosk_token
        answers = []
        for i in range(13):
            resp = self.url_open(url, data={'service_id': self.service.id},
                                 headers={'X-Forwarded-For':
                                          '10.9.%d.%d, 203.0.113.9' % (i, i)})
            answers.append(resp.json().get('status'))
        self.assertEqual(answers[:12], ['ok'] * 12)
        self.assertEqual(answers[12], 'error')

    # --- Webhook Wave des tickets ----------------------------------------

    def test_legacy_webhook_uses_the_socle_answers(self):
        """L'ancienne adresse répond comme le socle : 401 sur signature
        fausse (et non plus 403)."""
        resp = self.url_open('/api/queue/wave/webhook', data=b'{}', headers={
            'Content-Type': 'application/json', 'Wave-Signature': 'faux'})
        self.assertEqual(resp.status_code, 401)

    def test_cancelled_ticket_is_not_revived_by_wave(self):
        ticket = self._ticket()
        ticket.write({'payment_ref': 'SESS-CANCEL'})
        ticket.action_cancel()
        resp = self._webhook({'data': {'id': 'SESS-CANCEL',
                                       'payment_status': 'succeeded'}})
        self.assertEqual(resp.status_code, 200)
        ticket.invalidate_recordset()
        self.assertNotEqual(ticket.payment_state, 'paid')

    def test_partial_amount_is_not_confirmed(self):
        ticket = self._ticket()
        ticket.write({'payment_ref': 'SESS-PART'})
        self._webhook({'data': {'id': 'SESS-PART', 'amount': '100',
                                'payment_status': 'succeeded'}})
        ticket.invalidate_recordset()
        self.assertEqual(ticket.payment_state, 'pending')
        # Le bon montant, lui, confirme.
        self._webhook({'data': {'id': 'SESS-PART', 'amount': '5000',
                                'payment_status': 'succeeded'}})
        ticket.invalidate_recordset()
        self.assertEqual(ticket.payment_state, 'paid')

    def test_malformed_client_reference_is_not_a_500(self):
        """Une erreur 500 ferait rejouer Wave sans fin."""
        resp = self._webhook({'data': {'client_reference': 'ticket-abc',
                                       'payment_status': 'succeeded'}})
        self.assertEqual(resp.status_code, 200)

    # --- Preuve de paiement ----------------------------------------------

    def test_proof_must_be_an_image_or_a_pdf(self):
        ticket = self._ticket()
        res = self._call('/api/queue/ticket/pay', {
            'auth_token': self.TOKEN, 'ticket_id': ticket.id, 'method': 'proof',
            'proof': base64.b64encode(b'#!/bin/sh\nrm -rf /\n').decode()})
        self.assertEqual(res.get('status'), 'error')
        ticket.invalidate_recordset()
        self.assertEqual(ticket.payment_state, 'pending')
        res = self._call('/api/queue/ticket/pay', {
            'auth_token': self.TOKEN, 'ticket_id': ticket.id, 'method': 'proof',
            'proof': base64.b64encode(_PNG).decode()})
        self.assertEqual(res.get('status'), 'ok')
        self.assertEqual(res['ticket']['payment_state'], 'to_validate')

    # --- Identifiants illisibles -----------------------------------------

    def test_non_numeric_ids_answer_not_found(self):
        for endpoint in ('/api/queue/ticket/status', '/api/queue/ticket/cancel',
                         '/api/queue/ticket/pay', '/api/queue/ticket/checkin'):
            res = self._call(endpoint, {'auth_token': self.TOKEN,
                                        'ticket_id': 'abc'})
            self.assertEqual(res.get('status'), 'error', endpoint)
        res = self._call('/api/queue/ticket/create', {
            'auth_token': self.TOKEN, 'service_id': 'x1',
            'qr_token': self.location.qr_token})
        self.assertEqual(res.get('status'), 'error')

    # --- Encaissement direct ---------------------------------------------

    def test_checkout_uses_the_establishment_key(self):
        self.company.sudo().write({
            'wave_api_key': 'KEY-CLINIQUE', 'wave_api_secret': 'S',
            'wave_webhook_secret': 'H', 'wave_api_enabled': True})
        self.env['ir.config_parameter'].sudo().set_param(
            'queue_management.wave_api_key', 'KEY-PLATEFORME')
        ticket = self._ticket()
        seen = {}

        def fake_post(url, headers=None, data=None, timeout=None):
            seen.update(headers=headers, payload=json.loads(data))
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {'id': 'cos-1', 'wave_launch_url': 'https://pay.wave.com/c/cos-1'})

        with patch('odoo.addons.queue_payment.models.queue_wave.requests.post',
                   side_effect=fake_post):
            res = self._call('/api/queue/ticket/pay', {
                'auth_token': self.TOKEN, 'ticket_id': ticket.id, 'method': 'wave'})
        self.assertEqual(res.get('payment_url'), 'https://pay.wave.com/c/cos-1')
        self.assertEqual(seen['headers']['Authorization'], 'Bearer KEY-CLINIQUE')
        # Le retour mène au portail du site, pas à la page de l'APK.
        self.assertIn('/queue/u/%s' % self.location.qr_token,
                      seen['payload']['success_url'])
