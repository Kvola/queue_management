# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class QueueService(models.Model):
    """Une file d'attente / un service (« Cardiologie », « État civil »).

    Porte la numérotation des tickets : un préfixe (``code``) + un compteur
    réinitialisé chaque jour. La logique « qui passe ensuite ? » est centralisée
    ici dans ``_get_next_waiting`` pour pouvoir l'ajuster sans rien casser
    ailleurs.
    """

    _name = 'queue.service'
    _description = "File d'attente"
    _order = 'company_id, sequence, name'

    name = fields.Char("Nom de la file", required=True, translate=True)
    code = fields.Char(
        "Préfixe", required=True, size=4,
        help="Préfixe du numéro de ticket, ex. « B » → tickets B-001, B-002…",
    )
    sequence = fields.Integer("Séquence", default=10)
    active = fields.Boolean("Active", default=True)

    location_id = fields.Many2one(
        'queue.location', string="Site", required=True, index=True,
        ondelete='cascade',
    )
    # Dérivé du site → garantit la cohérence et alimente les record rules.
    company_id = fields.Many2one(
        'res.company', string="Établissement",
        related='location_id.company_id', store=True, index=True, readonly=True,
    )

    counter_ids = fields.Many2many(
        'queue.counter', 'queue_counter_service_rel', 'service_id', 'counter_id',
        string="Guichets desservant la file",
    )
    ticket_ids = fields.One2many('queue.ticket', 'service_id', string="Tickets")

    # Numérotation quotidienne. ``last_number`` est remis à 0 au premier ticket
    # d'un nouveau jour (cf. ``_next_number``).
    last_number = fields.Integer("Dernier n°", default=0, copy=False)
    last_number_date = fields.Date("Date du dernier n°", copy=False)

    # --- Rendez-vous (Phase 4b) ---
    # NB : les heures d'ouverture sont interprétées dans le fuseau du serveur
    # (UTC). Pour un déploiement hors UTC, prévoir une conversion de fuseau.
    appointment_enabled = fields.Boolean("Rendez-vous activés")
    slot_duration = fields.Integer(
        "Durée d'un créneau (min)", default=30,
        help="Découpage des plages d'ouverture en créneaux de cette durée.")
    slot_capacity = fields.Integer(
        "Capacité par créneau", default=1,
        help="Nombre de rendez-vous réservables sur un même créneau.")
    opening_hour_ids = fields.One2many(
        'queue.opening.hour', 'service_id', string="Plages d'ouverture")

    waiting_count = fields.Integer("En attente", compute='_compute_waiting_count')

    _code_uniq_per_location = models.Constraint(
        'UNIQUE(code, location_id)',
        "Le préfixe doit être unique par site.",
    )

    @api.depends('ticket_ids.state')
    def _compute_waiting_count(self):
        for service in self:
            service.waiting_count = len(
                service.ticket_ids.filtered(lambda t: t.state == 'waiting')
            )

    @api.constrains('code')
    def _check_code(self):
        for service in self:
            if service.code and not service.code.strip():
                raise ValidationError(_("Le préfixe ne peut pas être vide."))

    def _next_number(self):
        """Retourne le prochain numéro de ticket (ex. « B-042 »).

        Compteur réinitialisé chaque jour. Appelé sous le verrou de ligne pris
        par l'écriture concurrente d'Odoo ; suffisant pour la Phase 0. Un passage
        à ``ir.sequence`` avec verrou dédié sera fait si la charge l'exige.
        """
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.last_number_date != today:
            self.last_number_date = today
            self.last_number = 0
        self.last_number += 1
        return f"{(self.code or '?').strip().upper()}-{self.last_number:03d}"

    def _get_ordered_waiting(self):
        """Les tickets en attente de la file, triés dans l'ordre d'appel.

        Tri : priorité décroissante, puis ordre d'arrivée. Un rendez-vous dont
        l'heure est passée est traité au moins en priorité haute pour ne pas
        léser le client qui a réservé. C'est l'unique source de vérité de
        l'ordonnancement (réutilisée par le calcul de position du ticket).
        """
        self.ensure_one()
        waiting = self.ticket_ids.filtered(lambda t: t.state == 'waiting')
        return waiting.sorted(key=lambda t: t._scheduling_key())

    def _get_next_waiting(self):
        """Le prochain ticket à appeler pour cette file (ou recordset vide)."""
        self.ensure_one()
        return self._get_ordered_waiting()[:1]

    # --- Rendez-vous : créneaux & réservation -------------------------------

    @staticmethod
    def _float_to_time(value):
        hour = int(value)
        minute = int(round((value - hour) * 60))
        if minute == 60:
            hour, minute = hour + 1, 0
        return time(min(hour, 23), min(minute, 59))

    def _slots_for_date(self, day):
        """Créneaux d'une journée : liste ordonnée de (datetime, places libres).

        Ne renvoie que les créneaux entiers contenus dans une plage d'ouverture.
        ``day`` est une ``date``. Les datetimes renvoyés sont naïfs (UTC, comme
        le stockage Odoo).
        """
        self.ensure_one()
        if not self.appointment_enabled or self.slot_duration <= 0:
            return []
        hours = self.opening_hour_ids.filtered(
            lambda h: h.dayofweek == str(day.weekday()))
        if not hours:
            return []

        # Réservations déjà posées ce jour-là (toutes non clôturées).
        day_start = datetime.combine(day, time.min)
        day_end = datetime.combine(day, time.max)
        booked = {}
        for ticket in self.ticket_ids:
            if (ticket.channel == 'appointment' and ticket.scheduled_time
                    and ticket.state in ('scheduled', 'waiting', 'called', 'serving')
                    and day_start <= ticket.scheduled_time <= day_end):
                booked[ticket.scheduled_time] = booked.get(ticket.scheduled_time, 0) + 1

        step = timedelta(minutes=self.slot_duration)
        capacity = max(self.slot_capacity, 1)
        slots = []
        for window in hours.sorted(key=lambda h: h.hour_from):
            cursor = datetime.combine(day, self._float_to_time(window.hour_from))
            end = datetime.combine(day, self._float_to_time(window.hour_to))
            while cursor + step <= end:
                used = booked.get(cursor, 0)
                slots.append((cursor, max(capacity - used, 0)))
                cursor += step
        return slots

    def _book_appointment(self, partner, slot_dt):
        """Réserve un créneau et renvoie le ticket de rendez-vous créé."""
        self.ensure_one()
        if not self.appointment_enabled:
            raise UserError(_("Les rendez-vous ne sont pas activés pour cette file."))
        available = dict(self._slots_for_date(slot_dt.date()))
        if slot_dt not in available:
            raise UserError(_("Ce créneau n'existe pas."))
        if available[slot_dt] <= 0:
            raise UserError(_("Ce créneau est complet."))
        return self.env['queue.ticket'].create({
            'service_id': self.id,
            'partner_id': partner.id if partner else False,
            'channel': 'appointment',
            'scheduled_time': slot_dt,
            'state': 'scheduled',
        })

    def _avg_service_minutes(self, window=20):
        """Durée de service moyenne des ``window`` derniers tickets terminés.

        Moyenne glissante récente : s'adapte à l'affluence du moment. Retourne
        0.0 si l'historique est insuffisant (l'estimation est alors masquée).
        """
        self.ensure_one()
        done = self.env['queue.ticket'].search([
            ('service_id', '=', self.id),
            ('state', '=', 'done'),
            ('service_real_minutes', '>', 0),
        ], order='closed_at desc', limit=window)
        if not done:
            return 0.0
        return sum(done.mapped('service_real_minutes')) / len(done)

    def _notify_upcoming(self, threshold=2):
        """Prévient (push) les clients qui approchent de la tête de file.

        Une seule fois par ticket (flag ``soon_notified``) pour ne pas spammer.
        Appelé après chaque mouvement de file (appel, fin, absence, annulation).
        """
        for service in self:
            for idx, ticket in enumerate(service._get_ordered_waiting(), start=1):
                if idx > threshold:
                    break
                if not ticket.soon_notified:
                    ticket.soon_notified = True
                    ticket._notify(
                        "Bientôt votre tour",
                        "Vous êtes en position %d dans la file %s." % (idx, service.name),
                        {'type': 'soon', 'position': idx, 'service': service.name},
                    )
