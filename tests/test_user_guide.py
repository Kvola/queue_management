# -*- coding: utf-8 -*-
"""Le guide du visiteur — Kvla File, dans le catalogue.

Un guide se dégrade EN SILENCE : un gabarit renommé, et la page répond sans
rien rendre. Les deux pointeurs de la fiche du catalogue sont des CHAÎNES que
personne ne vérifie au chargement : ces tests le font.

`HttpCase` et non `TransactionCase` : un rendu PDF réel depuis un
`TransactionCase` fige la suite (wkhtmltopdf rappelle le serveur, qui attend
la transaction du test).
"""
import os
import re

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestUserGuide(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = cls.env.ref('queue_management.mobile_app_kvla_file')

    def test_the_app_points_to_an_existing_guide(self):
        self.assertTrue(self.env.ref(self.app.guide_template_xmlid,
                                     raise_if_not_found=False))
        report = self.env.ref(self.app.guide_report_xmlid,
                              raise_if_not_found=False)
        self.assertTrue(report)
        # Rendu sur `mobile.app`, sinon la route refuse (le rapport porterait
        # sur l'enregistrement d'un autre modèle au même identifiant).
        self.assertEqual(report.model, 'mobile.app')

    def test_guide_link_is_the_built_in_guide(self):
        self.assertEqual(self.app.guide_link, '/apps/kvla-file/guide')

    def test_guide_is_readable_without_an_account(self):
        """On lit le guide AVANT d'installer : il ne peut pas exiger de compte."""
        response = self.url_open('/apps/kvla-file/guide')
        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("Guide d'utilisation", body)
        # Le vocabulaire de l'écran, cité tel quel.
        for label in ('Prendre un ticket', 'Scanner le QR du site',
                      'Mes sites', 'Prendre rendez-vous',
                      'Choisissez un moyen de paiement',
                      'Preuve de paiement', 'Au guichet'):
            self.assertIn(label, body)
        # La version navigateur, pour qui n'a pas d'Android.
        self.assertIn('Ouvrir dans le navigateur', body)

    def test_guide_pdf_route_renders(self):
        response = self.url_open('/apps/kvla-file/guide.pdf')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Content-Type'), 'application/pdf')

    def test_the_report_really_produces_a_pdf(self):
        """Sans `force_report_rendering`, aucun octet de PDF ne serait produit."""
        pdf, content_type = self.env.ref(
            'queue_management.action_report_user_guide',
        ).with_context(force_report_rendering=True)._render_qweb_pdf(
            'queue_management.action_report_user_guide', res_ids=self.app.ids)
        self.assertEqual(content_type, 'pdf')
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_every_screenshot_of_the_guide_exists(self):
        """Une capture manquante ne lève RIEN : un cadre vide au milieu du
        texte, là où l'on montrait le geste."""
        source = self.env.ref('queue_management.user_guide_content').arch
        chemins = re.findall(r'''t-set="chemin"\s+t-value="'([^']+)'"''', source)
        self.assertGreaterEqual(len(chemins), 8, "Le guide a perdu ses captures.")
        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for chemin in chemins:
            self.assertTrue(chemin.startswith('queue_management/'), chemin)
            self.assertTrue(
                os.path.exists(os.path.join(racine, chemin.split('/', 1)[1])),
                "Capture absente : %s — relancez "
                "./sync_queue_guide_screenshots.sh" % chemin)

    def test_the_page_shows_the_screenshots(self):
        body = self.url_open('/apps/kvla-file/guide').text
        self.assertIn('/queue_management/static/guide/kvla-file-ticket.png', body)
        png = self.url_open('/queue_management/static/guide/kvla-file-ticket.png')
        self.assertEqual(png.status_code, 200)
        self.assertEqual(png.headers.get('Content-Type'), 'image/png')

    def test_the_printed_guide_embeds_its_screenshots(self):
        """Le PDF PORTE les images : wkhtmltopdf ne peut pas les redemander à
        un serveur occupé à rendre ce même rapport — l'impression réussirait
        alors sans une seule image."""
        pdf, _type = self.env.ref(
            'queue_management.action_report_user_guide',
        ).with_context(force_report_rendering=True)._render_qweb_pdf(
            'queue_management.action_report_user_guide', res_ids=self.app.ids)
        images = pdf.count(b'/Subtype /Image') + pdf.count(b'/Subtype/Image')
        self.assertGreaterEqual(images, 8)

    def test_the_printed_html_declares_its_encoding(self):
        """Ce que reçoit wkhtmltopdf doit dire « UTF-8 ».

        Sans le `div.article` de `web.basic_layout`, Odoo transmet le corps
        brut, sans `<meta charset>` : wkhtmltopdf le lit en Latin-1 et chaque
        accent du guide sort en « tÃ©lÃ©phone ». Rien ne lève ; il faut
        regarder ce qui part à l'impression.
        """
        report = self.env.ref('queue_management.action_report_user_guide')
        html = report._render_qweb_html(report.report_name, self.app.ids)[0]
        bodies, _ids, header, footer, _args = report._prepare_html(
            html, report_model=report.model)
        self.assertTrue(bodies)
        for body in bodies:
            self.assertIn('charset="utf-8"', body.lower().replace("'", '"'))

    def test_the_catalogue_page_offers_guide_and_browser_version(self):
        body = self.url_open('/apps/kvla-file').text
        self.assertIn('/apps/kvla-file/guide', body)
        self.assertIn('/queue/u', body)
