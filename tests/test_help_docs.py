# -*- coding: utf-8 -*-
import os

from odoo.modules import get_module_path
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHelpDocs(TransactionCase):
    """Le menu Aide pointe vers des guides qui existent réellement."""

    GUIDES = ('guide_client_mobile', 'guide_agent',
              'guide_responsable', 'guide_administrateur')

    def test_html_and_pdf_shipped(self):
        root = get_module_path('queue_management')
        for slug in self.GUIDES:
            self.assertTrue(os.path.isfile(
                os.path.join(root, 'static', 'docs', f'{slug}.html')), slug)
            self.assertTrue(os.path.isfile(
                os.path.join(root, 'docs', 'pdf', f'{slug}.pdf')), slug)

    def test_help_actions_target_static_files(self):
        for xmlid in ('action_help_client', 'action_help_agent',
                      'action_help_manager', 'action_help_admin'):
            action = self.env.ref('queue_management.%s' % xmlid)
            self.assertTrue(action.url.startswith(
                '/queue_management/static/docs/'), xmlid)
