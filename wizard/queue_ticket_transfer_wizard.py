# -*- coding: utf-8 -*-
from odoo import api, fields, models


class QueueTicketTransferWizard(models.TransientModel):
    """Transfert d'un ticket vers une autre file du même site."""

    _name = 'queue.ticket.transfer.wizard'
    _description = "Transférer un ticket de file"

    ticket_id = fields.Many2one(
        'queue.ticket', string="Ticket", required=True,
        default=lambda self: self.env.context.get('active_id'))
    location_id = fields.Many2one(related='ticket_id.location_id')
    current_service_id = fields.Many2one(
        related='ticket_id.service_id', string="Service actuel")
    new_service_id = fields.Many2one(
        'queue.service', string="Service de destination", required=True,
        domain="[('location_id', '=', location_id),"
               " ('id', '!=', current_service_id), ('active', '=', True)]")

    def action_transfer(self):
        self.ensure_one()
        self.ticket_id.action_transfer(self.new_service_id)
        return {'type': 'ir.actions.act_window_close'}
