# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class QueueCounter(models.Model):
    """Un guichet / poste de service (« Guichet 3 »).

    Un guichet appartient à un site et peut desservir plusieurs files. L'agent
    qui y est affecté appelle le client suivant via ``action_call_next``.
    """

    _name = 'queue.counter'
    _description = "Guichet"
    _inherit = ['mail.thread']
    _order = 'company_id, location_id, name'

    name = fields.Char("Nom du guichet", required=True, translate=True,
                       tracking=True)
    active = fields.Boolean("Actif", default=True, tracking=True)

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
        string="Services desservis",
    )
    agent_id = fields.Many2one('res.users', string="Agent titulaire",
                               tracking=True,
                               help="Affectation par défaut (organisation). "
                                    "La présence réelle passe par « Agents "
                                    "connectés » (console).")
    agent_ids = fields.Many2many(
        'res.users', 'queue_counter_agent_rel', 'counter_id', 'user_id',
        string="Agents connectés",
        help="Agents actuellement connectés à ce guichet via leur console. "
             "Plusieurs agents peuvent partager un guichet (binôme, "
             "formation).")

    current_ticket_id = fields.Many2one(
        'queue.ticket', string="Ticket en cours", copy=False,
        help="Ticket actuellement appelé ou en cours de traitement à ce guichet.",
    )
    current_ticket_state = fields.Selection(
        related='current_ticket_id.state', string="État du ticket en cours",
        help="Pilote la visibilité des boutons d'action du formulaire.")
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

    @api.onchange('location_id')
    def _onchange_location_id(self):
        """À la saisie : garde les files du nouveau site, et si rien ne reste,
        pré-remplit avec toutes les files actives du site (ajustable). Évite
        le piège du guichet créé sans file desservie."""
        for counter in self:
            if not counter.location_id:
                continue
            counter.service_ids = counter.service_ids.filtered(
                lambda s: s.location_id == counter.location_id)
            if not counter.service_ids:
                counter.service_ids = counter.location_id.service_ids.filtered(
                    'active')

    @api.constrains('service_ids', 'location_id')
    def _check_services_same_location(self):
        """Un guichet ne peut desservir que des files de SON site."""
        for counter in self:
            foreign = counter.service_ids.filtered(
                lambda s: s.location_id != counter.location_id)
            if foreign:
                raise ValidationError(_(
                    "Les files suivantes n'appartiennent pas au site de ce "
                    "guichet (%(site)s) : %(files)s.",
                    site=counter.location_id.display_name,
                    files=", ".join(foreign.mapped('name')),
                ))

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
        Itération explicite (pas de ``mapped(lambda)``) : sur un guichet en
        cours de création (onchange), ``service_ids`` est vide et Odoo 19
        passerait le recordset vide à la lambda → ``ensure_one()`` planterait.
        """
        self.ensure_one()
        candidates = self.env['queue.ticket']
        for service in self.service_ids:
            candidates |= service._get_next_waiting()
        return candidates.sorted(key=lambda t: t._scheduling_key())[:1]

    # ------------------------------------------------------------------
    # Console agent (client action Owl) : présence + données temps réel
    # ------------------------------------------------------------------

    def action_join(self):
        """L'utilisateur courant se connecte à CE guichet (et quitte
        automatiquement tout autre guichet — on ne tient qu'un poste à la
        fois)."""
        self.ensure_one()
        others = self.search([('agent_ids', 'in', self.env.uid),
                              ('id', '!=', self.id)])
        if others:
            others.write({'agent_ids': [(3, self.env.uid)]})
        if self.env.user not in self.agent_ids:
            self.write({'agent_ids': [(4, self.env.uid)]})
            self.message_post(body=_(
                "%s s'est connecté(e) au guichet.", self.env.user.name))
        return True

    def action_leave(self):
        """L'utilisateur courant quitte le guichet."""
        for counter in self:
            if self.env.user in counter.agent_ids:
                counter.write({'agent_ids': [(3, self.env.uid)]})
                counter.message_post(body=_(
                    "%s a quitté le guichet.", self.env.user.name))
        return True

    @api.model
    def get_console_data(self, counter_id=None):
        """Données de la console agent. Sans sudo : record rules appliquées
        (un agent ne voit que les guichets de ses établissements)."""
        counters = self.search([('active', '=', True)])
        mine = counters.filtered(lambda c: self.env.user in c.agent_ids)
        counter = (counters.filtered(lambda c: c.id == counter_id)
                   or mine or counters)[:1]
        data = {
            'counters': [{
                'id': c.id,
                'name': c.display_name,
                'location': c.location_id.name,
                'joined': self.env.user in c.agent_ids,
            } for c in counters],
            'counter_id': counter.id if counter else False,
        }
        if counter:
            ticket = counter.current_ticket_id
            data.update({
                'name': counter.name,
                'location': counter.location_id.name,
                'joined': self.env.user in counter.agent_ids,
                'agents': counter.agent_ids.mapped('name'),
                'services': counter.service_ids.mapped('name'),
                'busy': counter.state == 'busy',
                'ticket_id': ticket.id if ticket else False,
                'ticket': ticket.name if ticket else '',
                'ticket_state': ticket.state if ticket else '',
                'ticket_service': ticket.service_id.name if ticket else '',
                'ticket_partner': ticket.partner_id.name if ticket else '',
                'next_number': counter.next_number or '',
                'waiting': counter.waiting_count,
                # Paiement du ticket en cours (pour valider/encaisser en direct).
                'ticket_payment': ticket._console_payment() if ticket else False,
                # Paiements déclarés à distance sur les services du guichet
                # (Wave marchand avant l'arrivée…) — hors ticket en cours.
                'to_validate': [
                    t._console_payment(with_ticket=True)
                    for t in self.env['queue.ticket'].search([
                        ('service_id', 'in', counter.service_ids.ids),
                        ('payment_state', '=', 'to_validate'),
                        ('id', '!=', ticket.id),
                    ], limit=20)
                ],
            })
        return data

    def action_call_next(self):
        """Appelle le prochain client (waiting → called à ce guichet)."""
        self.ensure_one()
        if not self.service_ids:
            raise UserError(_(
                "Ce guichet ne dessert aucun service. Ouvrez sa fiche et "
                "ajoutez-en dans « Services desservis »."))
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
