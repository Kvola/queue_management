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

    # Aperçu pour la console agent : qui passe ensuite et combien attendent.
    next_ticket_id = fields.Many2one(
        'queue.ticket', string="Prochain", compute='_compute_next',
    )
    next_number = fields.Char("N° suivant", compute='_compute_next')
    waiting_count = fields.Integer("En attente", compute='_compute_next')

    @api.depends('current_ticket_id', 'current_ticket_id.state')
    def _compute_state(self):
        for counter in self:
            busy = counter.current_ticket_id and \
                counter.current_ticket_id.state in ('called', 'serving')
            counter.state = 'busy' if busy else 'free'

    @api.depends('service_ids', 'service_ids.ticket_ids.state',
                 'service_ids.ticket_ids.priority')
    def _compute_next(self):
        for counter in self:
            head = counter._peek_next()
            counter.next_ticket_id = head.id
            counter.next_number = head.name if head else ''
            counter.waiting_count = sum(counter.service_ids.mapped('waiting_count'))

    def _peek_next(self):
        """Le prochain ticket à appeler parmi toutes les files du guichet.

        On agrège les têtes de file des services desservis puis on les départage
        avec la même clé d'ordonnancement (priorité, ancienneté, RDV échu).
        """
        self.ensure_one()
        candidates = self.service_ids.mapped(lambda s: s._get_next_waiting())
        return candidates.sorted(key=lambda t: t._scheduling_key())[:1]

    def action_call_next(self):
        """Appelle le prochain client (waiting → called à ce guichet)."""
        self.ensure_one()
        if not self.service_ids:
            raise UserError(_("Ce guichet ne dessert aucune file."))
        if self.current_ticket_id and self.current_ticket_id.state in ('called', 'serving'):
            raise UserError(_("Terminez d'abord le client en cours à ce guichet."))
        ticket = self._peek_next()
        if not ticket:
            raise UserError(_("Aucun client en attente."))
        ticket.action_call(self)
        return True

    # --- Raccourcis console : agissent sur le ticket en cours ----------------

    def _require_current(self):
        self.ensure_one()
        if not self.current_ticket_id:
            raise UserError(_("Aucun ticket en cours à ce guichet."))
        return self.current_ticket_id

    def action_start(self):
        return self._require_current().action_start()

    def action_done(self):
        return self._require_current().action_done()

    def action_no_show(self):
        return self._require_current().action_no_show()

    def action_recall(self):
        return self._require_current().action_recall()
