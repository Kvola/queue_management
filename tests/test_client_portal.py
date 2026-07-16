# -*- coding: utf-8 -*-
import json

from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestClientPortalPages(HttpCase):

    def test_portal_page_renders(self):
        resp = self.url_open('/queue/u/abc123')
        self.assertEqual(resp.status_code, 200)
        self.assertIn("File d'attente", resp.text)
        self.assertIn('data-token="abc123"', resp.text)
        # Fonctions W2 présentes dans la page (rendez-vous + paiement par preuve).
        self.assertIn('apptModal', resp.text)
        self.assertIn('proofInput', resp.text)

    def test_generic_portal_renders(self):
        resp = self.url_open('/queue/u')
        self.assertEqual(resp.status_code, 200)

    def test_manifest(self):
        resp = self.url_open('/queue/u/abc123/manifest.webmanifest')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.text)
        self.assertEqual(data['start_url'], '/queue/u/abc123')
        self.assertEqual(data['display'], 'standalone')
        self.assertTrue(data['icons'])

    def test_service_worker(self):
        resp = self.url_open('/queue/sw.js')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('addEventListener', resp.text)
        self.assertIn('javascript', resp.headers.get('Content-Type', ''))


@tagged('post_install', '-at_install')
class TestClientPortalReport(TransactionCase):

    def test_qr_encodes_portal_url(self):
        loc = self.env['queue.location'].create({
            'name': 'Site QR web', 'company_id': self.env.company.id})
        self.assertTrue(loc.qr_token)
        html, ftype = self.env['ir.actions.report']._render_qweb_html(
            'queue_management.report_site_qr', loc.ids)
        html = html.decode() if isinstance(html, bytes) else html
        # Le QR encode désormais l'URL du portail, pas le jeton brut.
        self.assertIn('/queue/u/' + loc.qr_token, html)
