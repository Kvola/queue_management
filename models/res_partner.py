# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    """Lien inverse partenaire → tickets.

    Nécessaire pour la record rule de ``queue.customer`` : un responsable ne
    doit voir que les clients mobiles ayant au moins un ticket dans une de ses
    sociétés, et ce domaine se traverse via le partenaire miroir.
    """

    _inherit = 'res.partner'

    queue_ticket_ids = fields.One2many(
        'queue.ticket', 'partner_id', string="Tickets de file d'attente")
