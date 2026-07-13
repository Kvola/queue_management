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
        ('remote', "À distance"),
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
    # Machine à états — UNIQUE source de vérité des transitions autorisées.
    # Toute action passe par _transition() : aucun chemin incohérent possible,
    # y compris depuis un futur développement.
    ALLOWED_TRANSITIONS = {
        'scheduled': {'waiting', 'no_show', 'cancelled'},
        'waiting': {'called', 'cancelled'},
        # called → waiting : transfert vers une autre file (le client
        # redevient « en attente » ailleurs, le guichet est libéré).
        'called': {'serving', 'done', 'no_show', 'cancelled', 'waiting'},
        'serving': {'done', 'cancelled'},
        'done': set(),
        'no_show': {'waiting'},   # re-filer un absent qui se présente
        'cancelled': set(),
    }

    name = fields.Char("Numéro", required=True, copy=False, readonly=True, default="/")

    service_id = fields.Many2one(
        'queue.service', string="Service", required=True, index=True,
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

    # --- Paiement ---
    PAYMENT_STATE = [
        ('not_required', "Gratuit"),
        ('pending', "Paiement en attente"),
        ('paid', "Payé"),
        ('refunded', "Remboursé"),
    ]
    PAYMENT_METHOD = [
        ('cash', "Espèces"),
        ('mobile_money', "Mobile money"),
        ('card', "Carte"),
    ]
    payment_state = fields.Selection(
        PAYMENT_STATE, string="Paiement", default='not_required',
        required=True, copy=False, tracking=True, index=True)
    payment_amount = fields.Monetary(
        "Montant", currency_field='currency_id', copy=False)
    currency_id = fields.Many2one(
        related='service_id.currency_id', string="Devise", store=True)
    payment_method = fields.Selection(
        PAYMENT_METHOD, string="Moyen de paiement", copy=False)
    paid_at = fields.Datetime("Payé le", copy=False)
    payment_ref = fields.Char(
        "Référence de paiement", copy=False,
        help="Identifiant de la transaction (agrégateur mobile money, TPE…).")
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

    # Durées réelles (pour les statistiques) — figées par les horodatages.
    wait_real_minutes = fields.Float(
        "Attente réelle (min)", compute='_compute_durations', store=True,
        aggregator='avg', help="Du ticket pris à l'appel.")
    service_real_minutes = fields.Float(
        "Service réel (min)", compute='_compute_durations', store=True,
        aggregator='avg', help="Du début de service à la clôture.")
    # Estimation dynamique pour le client (non stockée).
    eta_minutes = fields.Integer(
        "Attente estimée (min)", compute='_compute_eta',
        help="Estimation basée sur la durée de service moyenne récente.")

    @api.depends('created_at', 'called_at', 'served_at', 'closed_at')
    def _compute_durations(self):
        for ticket in self:
            ticket.wait_real_minutes = (
                (ticket.called_at - ticket.created_at).total_seconds() / 60.0
                if ticket.called_at and ticket.created_at else 0.0)
            ticket.service_real_minutes = (
                (ticket.closed_at - ticket.served_at).total_seconds() / 60.0
                if ticket.closed_at and ticket.served_at else 0.0)

    @api.depends('state', 'position', 'service_id')
    def _compute_eta(self):
        for ticket in self:
            ticket.eta_minutes = ticket._estimated_wait_minutes()

    def _estimated_wait_minutes(self):
        """Estimation : position × durée de service moyenne / nb de guichets.

        Retourne 0 si le ticket n'attend pas ou si l'historique est insuffisant.
        """
        self.ensure_one()
        if self.state != 'waiting' or self.position <= 0:
            return 0
        avg = self.service_id._avg_service_minutes()
        if avg <= 0:
            return 0
        counters = max(len(self.service_id.counter_ids), 1)
        return int(round(self.position * avg / counters))

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
            if vals.get('service_id') and 'payment_state' not in vals:
                service = self.env['queue.service'].browse(vals['service_id'])
                if service.payment_required and service.price > 0:
                    vals['payment_state'] = 'pending'
                    vals.setdefault('payment_amount', service.price)
                else:
                    vals['payment_state'] = 'not_required'
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

    def _transition(self, new_state, vals=None):
        """Passe les tickets à ``new_state`` en validant la machine à états.

        Filet de sécurité générique : les actions gardent leurs messages
        d'erreur métier explicites, mais aucune écriture d'état incohérente
        ne peut passer par ici.
        """
        for ticket in self:
            if new_state not in self.ALLOWED_TRANSITIONS.get(ticket.state, set()):
                raise UserError(_(
                    "Transition impossible : %(vieux)s → %(nouveau)s (ticket %(nom)s).",
                    vieux=dict(self.STATE)[ticket.state],
                    nouveau=dict(self.STATE)[new_state],
                    nom=ticket.name,
                ))
        self.write(dict(vals or {}, state=new_state))
        return True

    def action_call(self, counter=None):
        """Appeler le ticket (waiting → called) et l'affecter à un guichet."""
        for ticket in self:
            if ticket.state != 'waiting':
                raise UserError(_("Seul un ticket en attente peut être appelé."))
            ticket._transition('called', {
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
            vals = {}
            if not ticket.name or ticket.name == '/':
                vals['name'] = ticket.service_id._next_number()
            ticket._transition('waiting', vals)
            ticket.service_id._notify_upcoming()
        return True

    @api.model
    def _cron_expire_appointments(self):
        """Marque « absent » les rendez-vous non enregistrés bien après l'heure.

        Le client est prévenu par push (best-effort) : sans cela, son RDV
        disparaît silencieusement et il l'apprend au guichet. Délai
        configurable (Paramètres → File d'attente), défaut 60 min.
        """
        from .res_config_settings import int_param
        delay = int_param(self.env, 'queue_management.no_show_delay_min', 60)
        deadline = fields.Datetime.now() - timedelta(minutes=max(delay, 1))
        overdue = self.search([
            ('state', '=', 'scheduled'),
            ('scheduled_time', '<', deadline),
        ])
        for ticket in overdue:
            ticket._transition('no_show', {'closed_at': fields.Datetime.now()})
            ticket._notify(
                "Rendez-vous expiré",
                "Votre rendez-vous « %s » n'a pas été enregistré à temps et a "
                "été annulé. Reprenez rendez-vous si besoin." % ticket.service_id.name,
                {'type': 'expired', 'service': ticket.service_id.name},
            )
        return True

    def action_start(self):
        """Début de la prise en charge au guichet (called → serving)."""
        for ticket in self:
            if ticket.state != 'called':
                raise UserError(_("Seul un ticket appelé peut démarrer."))
            ticket._transition('serving', {'served_at': fields.Datetime.now()})
        return True

    def action_done(self):
        """Service terminé (serving/called → done)."""
        for ticket in self:
            if ticket.state not in ('called', 'serving'):
                raise UserError(_("Ce ticket ne peut pas être terminé."))
            ticket._transition('done', {'closed_at': fields.Datetime.now()})
            ticket._release_counter()
            ticket.service_id._notify_upcoming()
        return True

    def action_no_show(self):
        """Client absent à l'appel (called → no_show)."""
        for ticket in self:
            if ticket.state != 'called':
                raise UserError(_("Seul un ticket appelé peut être marqué absent."))
            ticket._transition('no_show', {'closed_at': fields.Datetime.now()})
            ticket._release_counter()
            ticket.service_id._notify_upcoming()
        return True

    def action_cancel(self):
        """Annulation (par le client ou l'agent)."""
        for ticket in self:
            if ticket.state in ('done', 'no_show', 'cancelled'):
                raise UserError(_("Ce ticket est déjà clôturé."))
            ticket._transition('cancelled', {'closed_at': fields.Datetime.now()})
            ticket._release_counter()
            ticket.service_id._notify_upcoming()
        return True

    def action_transfer(self, new_service):
        """Transfère le ticket vers une autre file du MÊME site (le client
        s'est trompé de file, ou l'agent le réoriente à l'appel).

        Il conserve son heure d'arrivée (ancienneté → il ne refait pas la
        queue) mais reçoit un numéro de la file cible (son ancien numéro
        porterait le mauvais préfixe). S'il était appelé, le guichet est
        libéré et il redevient « en attente »."""
        self.ensure_one()
        if self.state not in ('waiting', 'called'):
            raise UserError(_(
                "Seul un ticket en attente ou appelé peut être transféré."))
        if new_service == self.service_id:
            raise UserError(_("Le ticket est déjà dans cette file."))
        if new_service.location_id != self.location_id:
            raise UserError(_(
                "Transfert impossible vers une file d'un autre site "
                "(le client est physiquement sur place)."))
        if not new_service.active:
            raise UserError(_("La file cible est archivée."))
        old_service, old_name = self.service_id, self.name
        vals = {
            'service_id': new_service.id,
            'name': new_service._next_number(),
            'soon_notified': False,
        }
        if self.state == 'called':
            self._release_counter()
            vals.update(counter_id=False, called_at=False)
            self._transition('waiting', vals)
        else:
            self.write(vals)
        self.message_post(body=_(
            "Transféré : %(vieux)s (%(file_vieille)s) → %(nouveau)s (%(file_neuve)s).",
            vieux=old_name, file_vieille=old_service.name,
            nouveau=self.name, file_neuve=new_service.name))
        self._notify(
            "Changement de file",
            "Votre ticket %s devient %s dans la file %s (position %d)." % (
                old_name, self.name, new_service.name, self.position),
            {'type': 'transferred'},
        )
        old_service._notify_upcoming()
        return True

    REQUEUE_WINDOW_HOURS = 2

    def action_requeue(self):
        """Re-met en file un client marqué absent qui se présente (no_show →
        waiting). Il conserve son numéro ET son heure d'arrivée d'origine
        (son ancienneté le replace correctement dans la file). Fenêtre
        limitée : au-delà, reprendre un ticket normalement."""
        now = fields.Datetime.now()
        for ticket in self:
            if ticket.state != 'no_show':
                raise UserError(_("Seul un ticket « Absent » peut être re-mis en file."))
            reference = ticket.closed_at or ticket.called_at
            if reference and now - reference > timedelta(hours=self.REQUEUE_WINDOW_HOURS):
                raise UserError(_(
                    "Absence trop ancienne (plus de %s h) : le client doit "
                    "reprendre un ticket.", self.REQUEUE_WINDOW_HOURS))
            ticket._transition('waiting', {
                'closed_at': False,
                'called_at': False,
                'counter_id': False,
                'soon_notified': False,
            })
            ticket._notify(
                "Vous êtes de retour dans la file",
                "Ticket %s — position %d." % (ticket.name, ticket.position),
                {'type': 'requeued'},
            )
        return True

    @api.model
    def _cron_auto_no_show(self):
        """Débloque les guichets : un ticket « appelé » resté sans réponse
        au-delà du délai configuré passe en Absent (guichet libéré, suivant
        notifié). Paramètres → File d'attente, défaut 10 min, 0 = désactivé."""
        from .res_config_settings import int_param
        delay = int_param(self.env, 'queue_management.auto_no_show_min', 10)
        if delay <= 0:
            return True
        deadline = fields.Datetime.now() - timedelta(minutes=delay)
        stuck = self.search([
            ('state', '=', 'called'),
            ('called_at', '<', deadline),
        ])
        for ticket in stuck:
            ticket._transition('no_show', {'closed_at': fields.Datetime.now()})
            ticket._release_counter()
            ticket._notify(
                "Vous avez été marqué absent",
                "Le ticket %s a été appelé sans réponse. Présentez-vous au "
                "guichet : l'agent peut vous re-mettre en file." % ticket.name,
                {'type': 'auto_no_show'},
            )
            ticket.service_id._notify_upcoming()
        return True

    def action_register_payment(self, method='cash', ref=False):
        """Enregistre le paiement d'un ticket (encaissement agent au guichet,
        ou confirmation mobile money). Idempotent : ne re-paie pas."""
        now = fields.Datetime.now()
        for ticket in self:
            if ticket.payment_state == 'paid':
                continue
            if ticket.payment_state == 'not_required':
                raise UserError(_("Ce service est gratuit : rien à encaisser."))
            ticket.write({
                'payment_state': 'paid',
                'payment_method': method,
                'paid_at': now,
                'payment_ref': ref or ticket.payment_ref,
            })
            ticket.message_post(body=_(
                "Paiement encaissé : %(montant)s (%(moyen)s).",
                montant=ticket.currency_id.format(ticket.payment_amount or 0.0)
                        if ticket.currency_id else (ticket.payment_amount or 0.0),
                moyen=dict(ticket.PAYMENT_METHOD).get(method, method)))
        return True

    def _release_counter(self):
        for ticket in self:
            if ticket.counter_id and ticket.counter_id.current_ticket_id == ticket:
                ticket.counter_id.current_ticket_id = False
