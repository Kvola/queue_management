# -*- coding: utf-8 -*-
import secrets

from odoo import _, api, fields, models


class QueueLocation(models.Model):
    """Site physique d'un établissement (un hôpital peut avoir plusieurs sites).

    C'est le point de rattachement du client : un QR code est affiché à l'entrée
    de chaque site ; en le scannant, l'application mobile sait à quel site (et
    donc à quelle société) rattacher le client, sans aucune saisie.
    """

    _name = 'queue.location'
    _description = "Site (file d'attente)"
    _order = 'company_id, name'

    name = fields.Char("Nom du site", required=True, translate=True)
    company_id = fields.Many2one(
        'res.company', string="Établissement", required=True, index=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean("Actif", default=True)

    street = fields.Char("Adresse")
    city = fields.Char("Ville")

    # Jeton secret encodé dans le QR code affiché à l'entrée. On stocke le jeton
    # (pas l'établissement en clair) pour éviter qu'une URL devinable ne rattache
    # un client au mauvais site.
    qr_token = fields.Char(
        "Jeton QR", copy=False, readonly=True, index=True,
        default=lambda self: secrets.token_urlsafe(16),
        help="Identifiant encodé dans le QR code du site. Régénérable.",
    )

    service_ids = fields.One2many('queue.service', 'location_id', string="Files")
    counter_ids = fields.One2many('queue.counter', 'location_id', string="Guichets")
    service_count = fields.Integer("Nb de files", compute='_compute_counts')
    counter_count = fields.Integer("Nb de guichets", compute='_compute_counts')

    _sql_constraints = [
        ('qr_token_uniq', 'unique(qr_token)', "Le jeton QR doit être unique."),
    ]

    @api.depends('service_ids', 'counter_ids')
    def _compute_counts(self):
        for location in self:
            location.service_count = len(location.service_ids)
            location.counter_count = len(location.counter_ids)

    def action_regenerate_qr_token(self):
        """Invalide le QR précédent (en cas de fuite ou d'affiche remplacée)."""
        for location in self:
            location.qr_token = secrets.token_urlsafe(16)
        return True

    def action_open_display(self):
        """Ouvre l'écran d'affichage public du site (à mettre en plein écran)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/queue/display/{self.qr_token}',
            'target': 'new',
        }
