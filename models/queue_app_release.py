# -*- coding: utf-8 -*-
"""Versions APK de l'application mobile client.

L'opérateur du SaaS téléverse l'APK dans le backend. Une seule version est
« publiée » à la fois : c'est elle qui est servie par la page publique
``/queue/app`` (et son lien direct ``/queue/app/download``). Le QR encodé sur
les écrans publics (borne, salle d'attente) pointe vers la page — pas vers le
binaire — si bien qu'un passage ultérieur au Play Store (paramètre système
``queue_management.app_store_url``) ne nécessite de réimprimer aucun QR.

Pattern repris de ``dms_ocr.dms_app_release`` (éprouvé), sans ``company_id`` :
l'app est la même pour tous les établissements du SaaS.
"""
import base64
import hashlib
from urllib.parse import quote

from odoo import api, fields, models
from odoo.exceptions import UserError


class QueueAppRelease(models.Model):
    _name = 'queue.app.release'
    _description = "Version APK de l'app mobile (file d'attente)"
    _order = 'released_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True, string="Désignation")
    version = fields.Char(
        "Version", required=True,
        help="Numéro de version sémantique, ex. 1.0.0.")
    build_number = fields.Integer("Build", default=1, required=True)
    release_notes = fields.Text("Notes de version")
    released_date = fields.Datetime(
        "Date de publication", default=fields.Datetime.now, required=True)
    is_active = fields.Boolean(
        "Version publiée", index=True,
        help="Une seule version publiée à la fois — celle servie sur la page "
             "d'installation publique et reflétée dans les QR codes.")

    apk_file = fields.Binary("Fichier APK", attachment=True, required=True)
    apk_file_name = fields.Char("Nom du fichier")
    apk_size_mb = fields.Float(
        "Taille (Mo)", readonly=True, compute='_compute_apk_meta', store=True)
    apk_sha256 = fields.Char(
        "SHA-256", readonly=True, compute='_compute_apk_meta', store=True,
        help="Empreinte du fichier — affichée sur la page d'installation pour "
             "vérifier l'intégrité de l'APK téléchargé.")

    download_count = fields.Integer(
        "Téléchargements", default=0, readonly=True,
        help="Incrémenté à chaque téléchargement via le lien public.")
    landing_url = fields.Char(
        "Lien d'installation", compute='_compute_urls',
        help="URL à partager / encoder en QR : page de présentation avec "
             "bouton de téléchargement et instructions.")
    qr_html = fields.Html(
        "QR code", compute='_compute_urls',
        sanitize=False, sanitize_attributes=False,
        help="À scanner ou imprimer (affiches). Pointe vers le lien "
             "d'installation.")

    def init(self):
        """Index partiel unique : au plus une release publiée."""
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS queue_app_release_active_uniq
                ON queue_app_release ((is_active))
                WHERE is_active = TRUE
        """)

    @api.depends('version', 'build_number')
    def _compute_name(self):
        for r in self:
            r.name = "File d'attente %s (build %s)" % (
                r.version or '?', r.build_number or 0)

    @api.depends('apk_file')
    def _compute_apk_meta(self):
        for r in self:
            if not r.apk_file:
                r.apk_size_mb = 0.0
                r.apk_sha256 = False
                continue
            try:
                raw = base64.b64decode(r.apk_file)
            except Exception:
                raw = b''
            r.apk_size_mb = round(len(raw) / (1024 * 1024), 2)
            r.apk_sha256 = hashlib.sha256(raw).hexdigest() if raw else False

    @api.model
    def _qr_src(self, size=320):
        """URL (même origine) de l'image QR pointant vers la landing."""
        return ('/report/barcode/?barcode_type=QR&value=%s&width=%d&height=%d'
                % (quote(self._landing_url(), safe=''), size, size))

    def _compute_urls(self):
        landing = self._landing_url()
        qr_src = self._qr_src()
        for r in self:
            r.landing_url = landing
            r.qr_html = (
                '<div style="display:inline-block;padding:8px;background:#fff;'
                'border:1px solid #dee2e6;border-radius:8px;">'
                '<img src="%s" alt="QR code" '
                'style="width:280px;height:280px;display:block;"/></div>'
            ) % qr_src

    # ------------------------------------------------------------------
    # Helpers publics (contrôleurs borne / affichage / landing)
    # ------------------------------------------------------------------

    @api.model
    def _landing_url(self):
        base = (self.env['ir.config_parameter'].sudo()
                .get_param('web.base.url') or '').rstrip('/')
        return '%s/queue/app' % base

    @api.model
    def _store_url(self):
        """URL de store (Play Store…) : si définie, la landing y redirige."""
        return (self.env['ir.config_parameter'].sudo()
                .get_param('queue_management.app_store_url') or '').strip()

    @api.model
    def _get_published(self):
        return self.search([('is_active', '=', True)], limit=1)

    @api.model
    def _landing_available(self):
        """L'app est-elle téléchargeable ? (pilote l'affichage des QR publics)"""
        return bool(self._store_url() or self._get_published())

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_publish(self):
        """Publie cette version (et dépublie toute autre)."""
        self.ensure_one()
        if not self.apk_file:
            raise UserError(
                "Aucun fichier APK attaché — impossible de publier cette version.")
        others = self.search([('is_active', '=', True), ('id', '!=', self.id)])
        if others:
            others.write({'is_active': False})
        self.write({'is_active': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Version publiée",
                'message': "%s est servie sur %s" % (self.name, self.landing_url),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_unpublish(self):
        self.write({'is_active': False})
        return True

    def increment_download(self):
        """Incrément atomique du compteur (appelé par le contrôleur public)."""
        self.ensure_one()
        self.env.cr.execute(
            "UPDATE queue_app_release SET download_count ="
            " COALESCE(download_count, 0) + 1 WHERE id = %s", (self.id,))
