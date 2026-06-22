# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class QueueCounter(models.Model):
    """Un guichet / poste de service (« Guichet 3 »).

    Un guichet appartient à un site et peut desservir plusieurs files. L'agent
    qui y est affecté appelle le client suivant via ``action_call_next``.
    """

    _name = 'queue.counter'
    _description = "Guichet"
    _order = 'company_id, location_id, name'

    name = fields.Char("Nom du guichet", required=True, translate=True)
    active = fields.Boolean("Actif", default=True)

    location_id = fields.Many2one(
        'queue.location', string="Site", required=True, index=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company', string="Établissement",
        related='location_id.company_id', store=True, index=True, readonly=True,
    )

    service_ids = fields.Many2many(
        'queue.service', 'queue_counter_service_rel', 'counter_id', 'service_id',
        string="Files desservies",
    )
    agent_id = fields.Many2one('res.users', string="Agent affecté")

    current_ticket_id = fields.Many2one(
        'queue.ticket', string="Ticket en cours", copy=False,
        help="Ticket actuellement appelé ou en cours de traitement à ce guichet.",
    )
    state = fields.Selection(
        [('free', "Libre"), ('busy', "Occupé")],
        string="État", compute='_compute_state',
    )

    @api.depends('current_ticket_id', 'current_ticket_id.state')
    def _compute_state(self):
        for counter in self:
            busy = counter.current_ticket_id and \
                counter.current_ticket_id.state in ('called', 'serving')
            counter.state = 'busy' if busy else 'free'

    def action_call_next(self):
        """Appelle le prochain client parmi toutes les files du guichet.

        On agrège les têtes de file des services desservis et on applique le même
        tri (priorité, ancienneté) pour choisir entre files.
        """
        self.ensure_one()
        if not self.service_ids:
            raise UserError(_("Ce guichet ne dessert aucune file."))

        now = fields.Datetime.now()
        candidates = self.service_ids.mapped(lambda s: s._get_next_waiting())

        def sort_key(ticket):
            weight = int(ticket.priority)
            if (ticket.channel == 'appointment' and ticket.scheduled_time
                    and ticket.scheduled_time <= now):
                weight = max(weight, 2)
            return (-weight, ticket.created_at or ticket.create_date)

        ticket = candidates.sorted(key=sort_key)[:1]
        if not ticket:
            raise UserError(_("Aucun client en attente."))

        ticket.action_call(self)
        return True
