# -*- coding: utf-8 -*-
"""Enveloppe bilingue de l'API mobile + jeton en en-tête Bearer.

Le client Dart partagé (ebng_odoo_client) lit ``success``/``error`` et porte
le jeton en ``Authorization: Bearer`` ; l'app historique lit ``status`` et
envoie ``auth_token`` dans le corps. Les deux doivent coexister.
"""
import json
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestApiEnvelope(HttpCase):

    def _rpc(self, path, params=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        resp = self.url_open(
            path,
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call',
                             'params': params or {}}),
            headers=headers)
        return resp.json().get('result') or {}

    def _customer_with_token(self):
        customer = self.env['queue.customer'].sudo().create(
            {'email': 'bearer.test@example.com'})
        token = 'a' * 64
        customer.write({
            'token': customer._hash(token),
            'token_expiry': fields.Datetime.now() + timedelta(days=1),
        })
        return customer, token

    def test_error_envelope_is_bilingual(self):
        # Endpoint authentifié appelé sans jeton → erreur dans LES DEUX formes
        result = self._rpc('/api/queue/tickets')
        self.assertEqual(result.get('status'), 'error')      # app historique
        self.assertIs(result.get('success'), False)          # client partagé
        self.assertEqual(result.get('error', {}).get('code'),
                         result.get('code'))
        self.assertTrue(result.get('error', {}).get('message'))

    def test_ok_envelope_is_bilingual_with_bearer(self):
        _customer, token = self._customer_with_token()
        result = self._rpc('/api/queue/tickets', token=token)
        self.assertEqual(result.get('status'), 'ok', result)
        self.assertIs(result.get('success'), True)

    def test_body_token_still_works(self):
        _customer, token = self._customer_with_token()
        result = self._rpc('/api/queue/tickets',
                           params={'auth_token': token})
        self.assertEqual(result.get('status'), 'ok', result)
