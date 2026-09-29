# -*- coding: utf-8 -*-
"""Les guides du personnel se lisent connecté, et selon son rôle.

Ils étaient servis depuis ``static/`` : lisibles sans compte, guide de
l'administrateur compris (réglages Wave, suspension d'un établissement).
"""
import os

from odoo.modules import get_module_path
from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.queue_management.controllers.guides import STAFF_GUIDES


@tagged('post_install', '-at_install')
class TestStaffGuides(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = new_test_user(
            cls.env, login='guide_agent',
            groups='base.group_user,queue_management.group_queue_agent')

    def test_every_registered_guide_ships_its_files(self):
        """Une entrée du registre sans fichier serait un 404 au clic."""
        self.assertIn('agent', STAFF_GUIDES)
        for name, (module, filename, group) in STAFF_GUIDES.items():
            root = get_module_path(module)
            if not root:
                continue  # module de la famille non installé ici
            for sub, ext in (('html', 'html'), ('pdf', 'pdf')):
                path = os.path.join(root, 'docs', sub, '%s.%s' % (filename, ext))
                self.assertTrue(os.path.isfile(path), '%s : %s' % (name, path))
            self.assertTrue(self.env.ref(group, raise_if_not_found=False), name)

    def test_no_guide_is_left_in_static(self):
        """Tout ce qui est sous static/ est public : aucun guide n'y reste."""
        root = get_module_path('queue_management')
        self.assertFalse(os.path.isdir(os.path.join(root, 'static', 'docs')))

    def test_anonymous_visitor_is_sent_to_login(self):
        response = self.url_open('/queue/guide/administrateur',
                                 allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn('/web/login', response.headers.get('Location', ''))

    def test_an_agent_reads_their_guide_not_the_admin_one(self):
        self.authenticate('guide_agent', 'guide_agent')
        page = self.url_open('/queue/guide/agent')
        self.assertEqual(page.status_code, 200)
        self.assertIn('text/html', page.headers.get('Content-Type', ''))
        # Styles en ligne autorisés, sinon la page s'affiche brute.
        self.assertIn("style-src 'unsafe-inline'",
                      page.headers.get('Content-Security-Policy', ''))
        pdf = self.url_open('/queue/guide/agent.pdf')
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        # Même réponse pour « interdit » et « inconnu ».
        self.assertEqual(self.url_open('/queue/guide/administrateur').status_code, 404)
        self.assertEqual(self.url_open('/queue/guide/nimporte').status_code, 404)

    def test_help_menu_points_to_the_protected_route(self):
        expected = {
            'action_help_agent': '/queue/guide/agent',
            'action_help_manager': '/queue/guide/responsable',
            'action_help_admin': '/queue/guide/administrateur',
            # Le guide du visiteur est public : celui du catalogue.
            'action_help_client': '/apps/kvla-file/guide',
        }
        for xmlid, url in expected.items():
            self.assertEqual(self.env.ref('queue_management.%s' % xmlid).url,
                             url, xmlid)
