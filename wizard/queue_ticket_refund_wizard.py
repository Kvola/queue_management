# -*- coding: utf-8 -*-
"""Rendre l'argent d'un ticket payé (service non rendu, ticket annulé…).

N'exécute aucun virement : le responsable rend l'argent (espèces, envoi Wave
depuis son téléphone) et le socle ``queue.refund`` en garde la trace, plafonnée
à ce que les paiements réglés ont réellement apporté.
"""
from odoo import _, api, fields, models
from odoo.addons.queue_payment.models.queue_payment import PAYMENT_METHOD


class QueueTicketRefundWizard(models.TransientModel):
    _name = 'queue.ticket.refund.wizard'
    _description = "Rembourser un ticket"

    ticket_id = fields.Many2one('queue.ticket', required=True, readonly=True)
    currency_id = fields.Many2one(related='ticket_id.currency_id')
    refundable = fields.Monetary(
        "Remboursable", compute='_compute_refundable',
        currency_field='currency_id')
    # Calculé depuis le ticket (tout le remboursable), modifiable : un
    # remboursement partiel reste possible.
    amount = fields.Monetary("Montant rendu", currency_field='currency_id',
                             compute='_compute_amount', store=True,
                             readonly=False)
    # Pas de `required` : un champ calculé stocké est écrit APRÈS l'insertion,
    # la contrainte NOT NULL tomberait avant. Le socle refuse de toute façon
    # un montant nul ou négatif.
    method = fields.Selection(PAYMENT_METHOD, "Rendu par", default='cash',
                              required=True)
    reason = fields.Text("Motif", required=True,
                         help="Pourquoi cet argent est rendu — il restera au "
                              "dossier du ticket.")

    @api.depends('ticket_id')
    def _compute_refundable(self):
        for wizard in self:
            wizard.refundable = wizard.ticket_id.sudo()._refundable_amount()

    @api.depends('ticket_id')
    def _compute_amount(self):
        for wizard in self:
            wizard.amount = wizard.ticket_id.sudo()._refundable_amount()

    def action_refund(self):
        self.ensure_one()
        # Le socle lève si le montant dépasse le remboursable ou si le motif
        # manque : le responsable voit pourquoi, rien n'est enregistré.
        self.ticket_id.sudo()._create_refund(
            self.amount, method=self.method, reason=self.reason,
            payment=self.ticket_id.sudo().payment_id)
        return {'type': 'ir.actions.act_window_close'}
