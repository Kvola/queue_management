# -*- coding: utf-8 -*-
import base64
import hashlib

from odoo.tests import HttpCase, tagged

# ~22 Ko : assez gros pour qu'une taille en Mo arrondie à 2 décimales soit > 0.
APK_BYTES = b'PK\x03\x04-fake-apk-for-tests-' * 1000


@tagged('post_install', '-at_install')
class TestAppRelease(HttpCase):
    """Distribution publique de l'app : landing, téléchargement, QR."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.release = cls.env['queue.app.release'].create({
            'version': '1.0.0',
            'build_number': 1,
            'release_notes': "Première version.",
            'apk_file': base64.b64encode(APK_BYTES),
            'apk_file_name': 'queue_mobile-v1.0.0.apk',
        })
        cls.location = cls.env['queue.location'].create({'name': "Site App"})

    def setUp(self):
        super().setUp()
        self.env['queue.rate.limit'].reset_key('queue_apk_dl:127.0.0.1')
        self.env['ir.config_parameter'].sudo().set_param(
            'queue_management.app_store_url', '')

    def test_sha256_and_size_computed(self):
        self.assertEqual(self.release.apk_sha256,
                         hashlib.sha256(APK_BYTES).hexdigest())
        self.assertGreater(self.release.apk_size_mb, 0)

    def test_publish_is_exclusive(self):
        other = self.release.copy({'version': '1.1.0',
                                   'apk_file': base64.b64encode(APK_BYTES)})
        self.release.action_publish()
        self.assertTrue(self.release.is_active)
        other.action_publish()
        self.assertTrue(other.is_active)
        self.assertFalse(self.release.is_active)
        (self.release | other).action_unpublish()

    def test_landing_404_without_published_release(self):
        self.release.action_unpublish()
        self.assertEqual(self.url_open('/queue/app').status_code, 404)
        self.assertEqual(self.url_open('/queue/app/download').status_code, 404)

    def test_landing_shows_published_release(self):
        self.release.action_publish()
        resp = self.url_open('/queue/app')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('1.0.0', resp.text)
        self.assertIn(self.release.apk_sha256, resp.text)
        # Défense en profondeur, comme les autres pages publiques.
        self.assertIn("default-src 'none'",
                      resp.headers.get('Content-Security-Policy', ''))
        self.release.action_unpublish()

    def test_download_serves_apk_and_counts(self):
        self.release.action_publish()
        before = self.release.download_count
        resp = self.url_open('/queue/app/download')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get('Content-Type'),
                         'application/vnd.android.package-archive')
        self.assertEqual(resp.content, APK_BYTES)
        self.release.invalidate_recordset(['download_count'])
        self.assertEqual(self.release.download_count, before + 1)
        self.release.action_unpublish()

    def test_landing_redirects_to_store_when_configured(self):
        self.release.action_publish()
        self.env['ir.config_parameter'].sudo().set_param(
            'queue_management.app_store_url',
            'https://play.google.com/store/apps/details?id=ci.queue')
        resp = self.url_open('/queue/app', allow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('play.google.com', resp.headers.get('Location', ''))
        self.release.action_unpublish()

    def test_public_pages_show_install_qr_only_when_available(self):
        # Sans release publiée ni store : pas de QR.
        self.release.action_unpublish()
        page = self.url_open('/queue/display/%s' % self.location.qr_token)
        self.assertNotIn('/report/barcode', page.text)
        # Release publiée : le QR apparaît sur l'affichage ET la borne.
        self.release.action_publish()
        for path in ('/queue/display/%s' % self.location.qr_token,
                     '/queue/kiosk/%s' % self.location.qr_token):
            page = self.url_open(path)
            self.assertIn('/report/barcode', page.text, path)
            self.assertIn('installer', page.text.lower(), path)
        self.release.action_unpublish()
