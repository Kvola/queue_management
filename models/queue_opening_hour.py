# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo import _


class QueueOpeningHour(models.Model):
    """Plage horaire d'ouverture d'une file pour les rendez-vous.

    Une ligne = un jour de la semaine + une fenêtre horaire. Les créneaux
    réservables sont générés à partir de ces plages, découpées selon la durée et
    la capacité configurées sur la file (cf. ``queue.service._slots_for_date``).
    """

    _name = 'queue.opening.hour'
    _description = "Plage horaire d'ouverture"
    _order = 'service_id, dayofweek, hour_from'

    DAYS = [
        ('0', "Lundi"), ('1', "Mardi"), ('2', "Mercredi"), ('3', "Jeudi"),
        ('4', "Vendredi"), ('5', "Samedi"), ('6', "Dimanche"),
    ]

    service_id = fields.Many2one(
        'queue.service', string="File", required=True, index=True,
        ondelete='cascade')
    company_id = fields.Many2one(
        related='service_id.company_id', store=True, index=True, readonly=True)
    dayofweek = fields.Selection(DAYS, string="Jour", required=True, default='0')
    hour_from = fields.Float("De", required=True, help="Ex. 8.5 = 08:30")
    hour_to = fields.Float("À", required=True, help="Ex. 17.0 = 17:00")

    @api.constrains('hour_from', 'hour_to')
    def _check_hours(self):
        for rec in self:
            if not (0 <= rec.hour_from < 24) or not (0 < rec.hour_to <= 24):
                raise ValidationError(_("Les heures doivent être comprises entre 0 et 24."))
            if rec.hour_from >= rec.hour_to:
                raise ValidationError(_("L'heure de début doit précéder l'heure de fin."))
