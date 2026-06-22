# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class QueueTicket(models.Model):
    """Le cœur du module : un passage d'un client dans une file.

    Cycle de vie :
        waiting → called → serving → done
                         ↘ no_show
        waiting/called/serving → cancelled
    """

    _name = 'queue.ticket'
    _description = "Ticket de file d'attente"
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    PRIORITY = [
        ('0', "Normale"),
        ('1', "Haute"),
        ('2', "Urgente"),
    ]
    CHANNEL = [
        ('mobile', "Mobile"),
        ('kiosk', "Borne"),
        ('appointment', "Rendez-vous"),
    ]
    STATE = [
        ('scheduled', "Programmé"),
        ('waiting', "En attente"),
        ('called', "Appelé"),
        ('serving', "En cours"),
        ('done', "Terminé"),
        ('no_show', "Absent"),
        ('cancelled', "Annulé"),
    ]

    name = fields.Char("Numéro", required=True, copy=False, readonly=True, default="/")

    service_id = fields.Many2one(
        'queue.service', string="File", required=True, index=True,
        ondelete='restrict',
    )
    # Dérivés du service → cohérence garantie + alimentent les record rules.
    location_id = fields.Many2one(
        'queue.location', string="Site",
        related='service_id.location_id', store=True, index=True, readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', string="Établissement",
        related='service_id.company_id', store=True, index=True, readonly=True,
    )

    partner_id = fields.Many2one(
        'res.partner', string="Client", index=True,
        help="Vide pour un ticket pris à la borne (anonyme).",
    )
    channel = fields.Selection(CHANNEL, string="Canal", required=True, default='mobile')
    priority = fields.Selection(PRIORITY, string="Priorité", required=True, default='0')
    state = fields.Selection(
        STATE, string="État", required=True, default='waiting',
        index=True, tracking=True,
    )

    counter_id = fields.Many2one('queue.counter', string="Guichet", copy=False)
    scheduled_time = fields.Datetime(
        "Heure de rendez-vous", copy=False,
        help="Renseignée uniquement pour les tickets de type Rendez-vous.",
    )

    # Horodatages : base des futures statistiques et de l'estimation du temps
    # d'attente (Phase 5). On ne les calcule pas encore, on les capture.
    created_at = fields.Datetime("Pris à", default=fields.Datetime.now, copy=False)
    called_at = fields.Datetime("Appelé à", copy=False)
    served_at = fields.Datetime("Début de service", copy=False)
    closed_at = fields.Datetime("Clôturé à", copy=False)

    position = fields.Integer(
        "Position", compute='_compute_position',
        help="Rang dans la file parmi les tickets en attente (1 = prochain).",
    )
    soon_notified = fields.Boolean(
        "Push « bientôt » envoyé", default=False, copy=False,
        help="Évite d'envoyer plusieurs fois la notification « bientôt votre tour ».",
    )

    @api.depends('state', 'priority', 'created_at', 'scheduled_time',
                 'service_id', 'service_id.ticket_ids.state')
    def _compute_position(self):
        for ticket in self:
            if ticket.state != 'waiting' or not ticket.service_id:
                ticket.position = 0
                continue
            ordered = ticket.service_id._get_ordered_waiting()
            ids = ordered.ids
            ticket.position = ids.index(ticket.id) + 1 if ticket.id in ids else 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Un rendez-vous (state 'scheduled') ne reçoit son numéro qu'au
            # check-in, quand il entre réellement dans la file du jour.
            if (vals.get('name', '/') == '/' and vals.get('service_id')
                    and vals.get('state', 'waiting') != 'scheduled'):
                service = self.env['queue.service'].browse(vals['service_id'])
                vals['name'] = service._next_number()
        return super().create(vals_list)

    def _scheduling_key(self):
        """Clé de tri d'un ticket dans la file (unique source de vérité).

        Priorité décroissante, puis ordre d'arrivée. Un rendez-vous dont l'heure
        est passée est remonté au moins en priorité haute. Réutilisée par la file
        (``_get_ordered_waiting``), le guichet et l'écran d'affichage.
        """
        self.ensure_one()
        weight = int(self.priority)
        if (self.channel == 'appointment' and self.scheduled_time
                and self.scheduled_time <= fields.Datetime.now()):
            weight = max(weight, 2)
        return (-weight, self.created_at or self.create_date)

    # --- Notifications push --------------------------------------------------

    def _customer(self):
        self.ensure_one()
        if not self.partner_id:
            return self.env['queue.customer']
        return self.env['queue.customer'].sudo().search(
            [('partner_id', '=', self.partner_id.id)], limit=1)

    def _notify(self, title, body, data=None):
        """Push best-effort au client du ticket (silencieux si pas de client)."""
        self.ensure_one()
        customer = self._customer()
        if customer:
            customer._push(title, body, dict(data or {}, ticket_id=self.id,
                                             ticket=self.name))

    # --- Transitions d'état --------------------------------------------------

    def action_call(self, counter=None):
        """Appeler le ticket (waiting → called) et l'affecter à un guichet."""
        for ticket in self:
            if ticket.state != 'waiting':
                raise UserError(_("Seul un ticket en attente peut être appelé."))
            ticket.write({
                'state': 'called',
                'counter_id': counter.id if counter else ticket.counter_id.id,
                'called_at': fields.Datetime.now(),
            })
            if counter:
                counter.current_ticket_id = ticket
            ticket._notify(
                "C'est à vous !",
                "Ticket %s — %s" % (ticket.name, (counter or ticket.counter_id).name or ''),
                {'type': 'called', 'counter': (counter or ticket.counter_id).name or '',
                 'service': ticket.service_id.name},
            )
            ticket.service_id._notify_upcoming()
        return True

    def action_recall(self):
        """Ré-annoncer un ticket déjà appelé (le client n'a pas réagi).

        Ne change pas d'état : rafraîchit ``called_at`` pour que l'écran de salle
        d'attente le remette en avant.
        """
        for ticket in self:
            if ticket.state != 'called':
                raise UserError(_("Seul un ticket appelé peut être ré-annoncé."))
            ticket.called_at = fields.Datetime.now()
        return True

    def action_check_in(self):
        """Enregistrement d'un rendez-vous à l'arrivée (scheduled → waiting).

        Le numéro de file n'est attribué qu'ici : le rendez-vous rejoint la file
        du jour et l'ordonnancement (remontée des RDV échus) prend le relais.
        """
        now = fields.Datetime.now()
        for ticket in self:
            if ticket.state != 'scheduled':
                raise UserError(_("Seul un rendez-vous programmé peut être enregistré."))
            if ticket.scheduled_time and now < ticket.scheduled_time - timedelta(hours=2):
                raise UserError(_("Enregistrement trop en avance par rapport à l'heure du rendez-vous."))
            vals = {'state': 'waiting'}
            if not ticket.name or ticket.name == '/':
                vals['name'] = ticket.service_id._next_number()
            ticket.write(vals)
            ticket.service_id._notify_upcoming()
        return True

    @api.model
    def _cron_expire_appointments(self):
        """Marque « absent » les rendez-vous non enregistrés bien après l'heure."""
        deadline = fields.Datetime.now() - timedelta(minutes=60)
        overdue = self.search([
            ('state', '=', 'scheduled'),
            ('scheduled_time', '<', deadline),
        ])
        for ticket in overdue:
            ticket.write({'state': 'no_show', 'closed_at': fields.Datetime.now()})
        return True

    def action_start(self):
        """Début de la prise en charge au guichet (called → serving)."""
        for ticket in self:
            if ticket.state != 'called':
                raise UserError(_("Seul un ticket appelé peut démarrer."))
            ticket.write({'state': 'serving', 'served_at': fields.Datetime.now()})
        return True

    def action_done(self):
        """Service terminé (serving/called → done)."""
        for ticket in self:
            if ticket.state not in ('called', 'serving'):
                raise UserError(_("Ce ticket ne peut pas être terminé."))
            ticket.write({'state': 'done', 'closed_at': fields.Datetime.now()})
            ticket._release_counter()
            ticket.service_id._notify_upcoming()
        return True

    def action_no_show(self):
        """Client absent à l'appel (called → no_show)."""
        for ticket in self:
            if ticket.state != 'called':
                raise UserError(_("Seul un ticket appelé peut être marqué absent."))
            ticket.write({'state': 'no_show', 'closed_at': fields.Datetime.now()})
            ticket._release_counter()
            ticket.service_id._notify_upcoming()
        return True

    def action_cancel(self):
        """Annulation (par le client ou l'agent)."""
        for ticket in self:
            if ticket.state in ('done', 'no_show', 'cancelled'):
                raise UserError(_("Ce ticket est déjà clôturé."))
            ticket.write({'state': 'cancelled', 'closed_at': fields.Datetime.now()})
            ticket._release_counter()
            ticket.service_id._notify_upcoming()
        return True

    def _release_counter(self):
        for ticket in self:
            if ticket.counter_id and ticket.counter_id.current_ticket_id == ticket:
                ticket.counter_id.current_ticket_id = False
