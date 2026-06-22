# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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

    waiting_count = fields.Integer("En attente", compute='_compute_waiting_count')

    _sql_constraints = [
        ('code_uniq_per_location', 'unique(code, location_id)',
         "Le préfixe doit être unique par site."),
    ]

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
        now = fields.Datetime.now()
        waiting = self.ticket_ids.filtered(lambda t: t.state == 'waiting')

        def sort_key(ticket):
            weight = int(ticket.priority)
            if (ticket.channel == 'appointment' and ticket.scheduled_time
                    and ticket.scheduled_time <= now):
                weight = max(weight, 2)
            return (-weight, ticket.created_at or ticket.create_date)

        return waiting.sorted(key=sort_key)

    def _get_next_waiting(self):
        """Le prochain ticket à appeler pour cette file (ou recordset vide)."""
        self.ensure_one()
        return self._get_ordered_waiting()[:1]
