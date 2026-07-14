# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    wave_payment_link = fields.Char(
        "Lien de paiement Wave",
        help="Lien marchand Wave de la compagnie pour encaisser ses paiements "
             "(ex. https://pay.wave.com/m/M_ci_xxxx/c/ci/). Le montant est "
             "ajouté automatiquement (?amount=…). Vide → lien Wave par défaut "
             "de la plateforme.")
