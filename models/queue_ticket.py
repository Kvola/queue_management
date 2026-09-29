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
    # Remboursable par le socle (``queue.refund``) : trace, plafond, crochets.
    _inherit = ['mail.thread', 'queue.refundable.mixin']
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
        ('to_validate', "À valider"),
        ('paid', "Payé"),
        ('refunded', "Remboursé"),
    ]
    PAYMENT_METHOD = [
        ('wave', "Wave"),
        ('counter', "Au guichet"),
        ('proof', "Preuve de paiement"),
        # Valeurs héritées (anciens tickets / API mobile v1).
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
        help="Identifiant de la transaction (Wave, virement, TPE…).")
    # L'argent passe par le socle : ``queue.payment`` est la seule source de
    # vérité (commissions, imputations, remboursements, webhook Wave). Les
    # champs ci-dessus restent le VOCABULAIRE du ticket — celui que lisent
    # l'app, la console et le portail — et ne sont écrits que par les crochets
    # que le socle déclenche (``_on_payment_*``).
    payment_id = fields.Many2one(
        'queue.payment', string="Paiement", copy=False, readonly=True,
        index=True, groups='queue_management.group_queue_manager',
        help="Encaissement en cours ou réglé de ce ticket (socle de paiement).")
    # Les remboursements (hérités du mixin) sont l'affaire du responsable : un
    # agent n'a pas accès à ``queue.refund``, lire ces champs lui lèverait une
    # erreur d'accès à l'ouverture d'un ticket.
    refund_ids = fields.Many2many(groups='queue_management.group_queue_manager')
    refund_count = fields.Integer(groups='queue_management.group_queue_manager')
    # La preuve vit sur le paiement : elle y reste après un rejet, comme
    # pièce du dossier, sans plus s'afficher sur le ticket.
    payment_proof = fields.Binary(
        "Preuve de paiement", related='payment_id.proof', readonly=True)
    payment_proof_filename = fields.Char(
        related='payment_id.proof_filename', readonly=True)
    payment_submitted_at = fields.Datetime(
        "Paiement déclaré le", copy=False,
        help="Quand le client a déclaré son paiement (à valider par le guichet).")
    payment_validated_by = fields.Many2one(
        'res.users', string="Validé par", copy=False, readonly=True)
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
        # L'ordre d'une file est calculé UNE fois par file, puis lu pour chaque
        # ticket : le recalculer ticket par ticket rendait la liste des tickets
        # (ou « Mes tickets » d'un client) quadratique en taille de file.
        ranks = {}
        for ticket in self:
            if ticket.state != 'waiting' or not ticket.service_id:
                ticket.position = 0
                continue
            service = ticket.service_id
            if service.id not in ranks:
                ranks[service.id] = {
                    tid: rank for rank, tid in enumerate(
                        service._get_ordered_waiting().ids, start=1)}
            ticket.position = ranks[service.id].get(ticket._origin.id, 0)

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
        # L'identifiant départage deux tickets pris dans la même seconde (un
        # afflux à la borne) : sans lui, leur ordre dépendait de l'ordre de
        # lecture en base, et deux écrans pouvaient appeler dans un ordre
        # différent.
        return (-weight, self.created_at or self.create_date, self._origin.id or 0)

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

    def _console_payment(self, with_ticket=False):
        """Résumé paiement pour la console agent (validation en direct).

        Retourne False si rien à faire (gratuit ou déjà payé). ``with_ticket``
        ajoute le numéro/service (pour la liste des paiements déclarés).
        """
        self.ensure_one()
        if self.payment_state not in ('pending', 'to_validate'):
            return False
        data = {
            'ticket_id': self.id,
            'state': self.payment_state,
            'amount': self._amount_label(),
            'method': dict(self.PAYMENT_METHOD).get(self.payment_method, ''),
            'ref': self.payment_ref or '',
            'has_proof': bool(self.payment_proof),
        }
        if with_ticket:
            data.update(name=self.name, service=self.service_id.name,
                        partner=self.partner_id.name or '')
        return data

    def _amount_label(self):
        self.ensure_one()
        if self.currency_id:
            return self.currency_id.format(self.payment_amount or 0.0)
        return str(self.payment_amount or 0.0)

    # ------------------------------------------------------------------
    # Paiement — par le socle ``queue.payment``
    #
    # Chaque geste (déclaration du client, validation, rejet, encaissement
    # direct, webhook Wave) agit sur le paiement du socle ; le ticket n'est
    # mis à jour QUE par les crochets ``_on_payment_*`` que le socle appelle.
    # Un seul chemin d'écriture : un webhook rejoué ou une double validation
    # ne peut plus créditer deux fois, et commissions, remboursements et
    # rapprochement Wave valent pour les tickets comme pour le reste.
    # ------------------------------------------------------------------

    _OPEN_PAYMENT_STATES = ('draft', 'pending', 'to_validate')

    def _payment_partner(self):
        self.ensure_one()
        return self.partner_id

    def _current_payment(self, method=None):
        """Le paiement du socle de ce ticket, créé au besoin.

        Réutilisé s'il est encore ouvert pour le bon montant (ou déjà réglé) ;
        un paiement rejeté, annulé ou d'un autre montant n'est jamais repris.
        """
        self.ensure_one()
        ticket = self.sudo()
        payment = ticket.payment_id
        currency = ticket.currency_id or ticket.company_id.currency_id
        if payment and (payment.state == 'paid' or (
                payment.state in self._OPEN_PAYMENT_STATES
                and currency.compare_amounts(payment.amount,
                                             ticket.payment_amount) == 0)):
            if method and payment.state != 'paid' and payment.method != method:
                payment.method = method
            return payment
        payment = self.env['queue.payment'].sudo().create({
            'company_id': ticket.company_id.id,
            'currency_id': currency.id,
            'partner_id': ticket.partner_id.id or False,
            'amount': ticket.payment_amount,
            'method': method or 'counter',
            'state': 'pending',
            'res_model': self._name,
            'res_id': ticket.id,
        })
        # Commission du prestataire (Wave…) selon les réglages de la société :
        # sans taux réglé, elle est nulle et rien ne change.
        payment._apply_provider_fee()
        ticket.payment_id = payment
        return payment

    def _mark_paid(self, method, ref=False, by_user=None):
        """Confirme le paiement du ticket (encaissement direct, webhook).
        Idempotent : un ticket payé le reste, rien n'est recrédité."""
        self.ensure_one()
        if self.payment_state == 'paid':
            return
        payment = self._current_payment(method)
        if ref:
            ref = self.env['queue.wave.mixin'].sudo()._wave_safe_ref(payment, ref)
        payment._mark_paid(ref=ref or None, by_user=by_user or self.env.user)

    def action_register_payment(self, method='counter', ref=False):
        """Encaissement DIRECT par l'agent au guichet (l'agent est le
        validateur : le paiement passe payé immédiatement). Idempotent."""
        for ticket in self:
            if ticket.payment_state == 'paid':
                continue
            if ticket.payment_state == 'not_required':
                raise UserError(_("Ce service est gratuit : rien à encaisser."))
            payment = ticket._current_payment(method)
            if ref:
                payment._check_ref_unused(ref)
                payment.provider_ref = ref
            # `sudo()` garde l'utilisateur : c'est bien l'agent qui valide.
            payment.action_validate()
        return True

    def _submit_payment(self, method, ref=False, proof=False, proof_filename=False):
        """Le CLIENT déclare un paiement (Wave marchand, au guichet, ou preuve).

        Résultat : « à valider » — un agent doit confirmer au guichet. Seule
        l'API Wave (voie directe) court-circuite cette étape, gérée ailleurs.
        """
        self.ensure_one()
        if self.payment_state in ('paid', 'not_required'):
            raise UserError(_("Ce ticket n'attend pas de paiement."))
        if method not in ('wave', 'counter', 'proof'):
            raise UserError(_("Moyen de paiement inconnu."))
        if method == 'proof' and not proof:
            raise UserError(_("Joignez une preuve de paiement."))
        payment = self._current_payment(method)
        # Le socle borne la preuve et refuse une référence déjà déclarée.
        payment._submit(method=method, ref=ref or None, proof=proof or None,
                        proof_filename=proof_filename or ('preuve' if proof else None))
        self.sudo().write({
            'payment_state': 'to_validate',
            'payment_method': method,
            'payment_submitted_at': fields.Datetime.now(),
            'payment_ref': ref or self.payment_ref,
        })
        labels = {'wave': _("Wave marchand"), 'counter': _("au guichet"),
                  'proof': _("preuve de paiement")}
        self.message_post(body=_(
            "Le client a déclaré un paiement (%(moyen)s) — à valider au guichet.",
            moyen=labels.get(method, method)))
        return True

    def action_validate_payment(self):
        """L'agent VALIDE un paiement déclaré (à valider → payé)."""
        for ticket in self:
            if ticket.payment_state != 'to_validate':
                raise UserError(_("Seul un paiement « à valider » peut être validé."))
            ticket._current_payment().action_validate()
        return True

    def action_reject_payment(self):
        """L'agent REJETTE un paiement déclaré (à valider → en attente)."""
        for ticket in self:
            if ticket.payment_state != 'to_validate':
                raise UserError(_("Seul un paiement « à valider » peut être rejeté."))
            ticket._current_payment().action_reject(
                reason=_("Rejeté au guichet par %s.", ticket.env.user.name))
        return True

    # --- Crochets appelés par ``queue.payment`` ------------------------------

    def _on_payment_paid(self, payment):
        for ticket in self:
            if ticket.payment_state == 'paid':
                continue
            methods = dict(self.PAYMENT_METHOD)
            ticket.write({
                'payment_state': 'paid',
                'payment_id': payment.id,
                'payment_method': payment.method if payment.method in methods
                else ticket.payment_method,
                'paid_at': payment.paid_at or fields.Datetime.now(),
                'payment_ref': payment.provider_ref or ticket.payment_ref,
                'payment_validated_by': (payment.validated_by
                                         or self.env.user).id,
            })
            ticket.message_post(body=_(
                "Paiement confirmé : %(montant)s (%(moyen)s).",
                montant=ticket._amount_label(),
                moyen=methods.get(ticket.payment_method,
                                  ticket.payment_method or '—')))
            if ticket.state == 'cancelled':
                # L'argent est arrivé (Wave confirme après coup) sur un ticket
                # annulé : on ne ressuscite pas le ticket, on le dit.
                ticket.message_post(body=_(
                    "Ce ticket était annulé : le paiement reçu est à "
                    "rembourser."))

    def _on_payment_rejected(self, payment):
        for ticket in self:
            if ticket.payment_state != 'to_validate':
                continue
            ticket.write({'payment_state': 'pending', 'payment_id': False})
            ticket.message_post(body=_(
                "Paiement rejeté (%(motif)s) — le client doit régler à nouveau.",
                motif=payment.rejection_reason or _("motif non précisé")))

    def _on_payment_cancelled(self, payment):
        for ticket in self:
            if ticket.payment_state == 'to_validate':
                ticket.write({'payment_state': 'pending', 'payment_id': False})

    def _on_payment_reverted(self, payment):
        """Une validation défaite (preuve falsifiée découverte après coup)."""
        for ticket in self:
            if ticket.payment_state != 'paid':
                continue
            ticket.write({'payment_state': 'pending', 'payment_id': False,
                          'paid_at': False, 'payment_validated_by': False})
            ticket.message_post(body=_(
                "Validation du paiement défaite : le ticket est de nouveau à "
                "régler."))

    # --- Remboursement (socle ``queue.refund``) -------------------------------

    def _refundable_amount(self):
        """On ne rend jamais plus que ce que les paiements réglés ont apporté."""
        self.ensure_one()
        paid = sum(self.env['queue.payment'].sudo().search([
            ('res_model', '=', self._name), ('res_id', '=', self.id),
            ('state', '=', 'paid')]).mapped('amount'))
        return max(0.0, paid - self._refunded_total())

    def _on_refund_registered(self, refund):
        super()._on_refund_registered(refund)
        if self.payment_state == 'paid' and self.currency_id.is_zero(
                self._refundable_amount()):
            self.payment_state = 'refunded'

    def _on_refund_cancelled(self, refund):
        super()._on_refund_cancelled(refund)
        if self.payment_state == 'refunded':
            self.payment_state = 'paid'

    def action_open_refund_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Rembourser"),
            'res_model': 'queue.ticket.refund.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id},
        }

    def _release_counter(self):
        for ticket in self:
            if ticket.counter_id and ticket.counter_id.current_ticket_id == ticket:
                ticket.counter_id.current_ticket_id = False
