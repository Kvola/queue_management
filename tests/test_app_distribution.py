# -*- coding: utf-8 -*-
"""Kvla File se distribue par le catalogue, sans casser un seul QR imprimé.

`/queue/app` est encodée dans les QR affichés dans les salles d'attente :
elle doit mener quelque part, pour toujours.
"""
from odoo.tests import HttpCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestAppDistribution(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = cls.env.ref('queue_management.mobile_app_kvla_file')
        cls.location = cls.env['queue.location'].create({'name': 'Hall QR'})
        cls.env['ir.config_parameter'].sudo().set_param(
            'queue_management.app_store_url', False)

    def _location(self, path):
        response = self.url_open(path, allow_redirects=False)
        self.assertEqual(response.status_code, 302, path)
        return response.headers['Location']

    def test_the_app_is_in_the_catalogue(self):
        self.assertEqual(self.app.slug, 'kvla-file')
        self.assertEqual(self.app.name, 'Kvla File')
        self.assertTrue(self.app.icon)
        # La version navigateur suffit à la rendre distribuable, APK ou pas.
        self.assertTrue(self.app.is_distributable())
        self.assertIn('Kvla File', self.url_open('/apps').text)

    def test_printed_qr_address_leads_to_the_catalogue(self):
        self.assertTrue(self._location('/queue/app').endswith('/apps/kvla-file'))
        self.assertTrue(self._location('/queue/app/download')
                        .endswith('/apps/kvla-file/download'))

    def test_a_store_address_takes_over_without_reprinting(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'queue_management.app_store_url',
            'https://play.google.com/store/apps/details?id=ci.queue.queue_mobile')
        self.assertTrue(self._location('/queue/app').startswith(
            'https://play.google.com/'))

    def test_public_screens_show_the_install_qr(self):
        """Borne et écran de salle proposent l'app — dès maintenant, car la
        version navigateur existe même sans APK publié."""
        token = self.location.qr_token
        for path in ('/queue/kiosk/%s' % token, '/queue/display/%s' % token):
            body = self.url_open(path).text
            self.assertIn('/report/barcode/?barcode_type=QR', body, path)
            self.assertIn('%2Fqueue%2Fapp', body, path)

    def test_the_release_menu_opens_on_kvla_file(self):
        """Le contexte d'une action est évalué par le NAVIGATEUR : un `ref()`
        écrit en clair y lèverait au premier clic."""
        action = self.env.ref('queue_management.action_queue_app_releases')
        context = safe_eval(action.context)
        self.assertEqual(context['default_app_id'], self.app.id)

    def test_the_operator_can_publish(self):
        """L'administrateur système publiait `queue.app.release` ; il publie
        désormais les versions du catalogue, sans autre groupe à lui donner."""
        Release = self.env['mobile.app.release'].with_user(
            self.env.ref('base.user_admin'))
        self.assertTrue(Release.has_access('create'))
