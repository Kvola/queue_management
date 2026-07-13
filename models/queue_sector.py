# -*- coding: utf-8 -*-
"""Catalogue : secteurs d'activité et modèles de services.

Accélère l'onboarding — au lieu de saisir ses services un par un, un nouvel
établissement choisit son secteur (« Santé », « Administration »…) et hérite
d'une liste de services types (nom, préfixe, canaux, tarif) qu'il ajuste. Les
modèles sont un simple point de départ : rien n'est verrouillé.
"""
from odoo import api, fields, models


class QueueSector(models.Model):
    _name = 'queue.sector'
    _description = "Secteur d'activité"
    _order = 'sequence, name'

    name = fields.Char("Secteur", required=True, translate=True)
    sequence = fields.Integer("Séquence", default=10)
    description = fields.Char("Description", translate=True)
    active = fields.Boolean("Actif", default=True)
    template_ids = fields.One2many(
        'queue.service.template', 'sector_id', string="Modèles de services")
    template_count = fields.Integer(
        "Nb de modèles", compute='_compute_template_count')

    @api.depends('template_ids')
    def _compute_template_count(self):
        for sector in self:
            sector.template_count = len(sector.template_ids)


class QueueServiceTemplate(models.Model):
    _name = 'queue.service.template'
    _description = "Modèle de service"
    _order = 'sector_id, sequence, name'

    name = fields.Char("Nom du service", required=True, translate=True)
    code = fields.Char("Préfixe", required=True, size=4,
                       help="Préfixe des numéros de ticket, ex. « B ».")
    sector_id = fields.Many2one('queue.sector', string="Secteur", required=True,
                                ondelete='cascade', index=True)
    sequence = fields.Integer("Séquence", default=10)

    remote_enabled = fields.Boolean("Tickets à distance")
    appointment_enabled = fields.Boolean("Rendez-vous")
    payment_required = fields.Boolean("Paiement requis")
    price = fields.Monetary("Tarif", currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', string="Devise",
        default=lambda self: self.env.company.currency_id)

    def _to_service_vals(self, location, sequence=None):
        """Valeurs pour créer un ``queue.service`` réel depuis ce modèle."""
        self.ensure_one()
        return {
            'name': self.name,
            'code': self.code,
            'location_id': location.id,
            'sequence': sequence if sequence is not None else self.sequence,
            'remote_enabled': self.remote_enabled,
            'appointment_enabled': self.appointment_enabled,
            'payment_required': self.payment_required,
            'price': self.price,
            'currency_id': self.currency_id.id,
        }
