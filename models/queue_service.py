# models/queue_service.py
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


class QueueService(models.Model):
    _name = "queue.service"
    _inherit = ["mail.thread", "mail.activity.mixin"]  # Ajout du tracking
    _description = "Service de File d'Attente"
    _order = "sequence, name"

    name = fields.Char("Nom du Service", required=True)
    description = fields.Text("Description")
    sequence = fields.Integer("Séquence", default=10)
    active = fields.Boolean("Actif", default=True)

    # Configuration
    max_tickets_per_day = fields.Integer("Max tickets par jour", default=100)
    estimated_service_time = fields.Integer("Temps service estimé (min)", default=15)
    working_hours_start = fields.Float("Heure d'ouverture", default=9.0)
    working_hours_end = fields.Float("Heure de fermeture", default=18.0)

    # Statuts
    is_open = fields.Boolean("Service ouvert", default=True)
    current_ticket_number = fields.Integer("Numéro ticket actuel", default=0)
    next_ticket_number = fields.Integer(
        "Prochain numéro", compute="_compute_next_ticket"
    )

    # Relations
    ticket_ids = fields.One2many("queue.ticket", "service_id", "Tickets")
    waiting_ticket_ids = fields.One2many(
        "queue.ticket",
        "service_id",
        domain=[("state", "=", "waiting")],
        string="Tickets en attente",
    )

    # Statistiques
    total_tickets_today = fields.Integer(
        "Tickets aujourd'hui", compute="_compute_stats"
    )
    waiting_count = fields.Integer("En attente", compute="_compute_stats", store=True)
    avg_waiting_time = fields.Float(
        "Temps d'attente moyen (min)", compute="_compute_stats"
    )

    # Nouveaux champs pour amélioration
    allow_online_booking = fields.Boolean(
        "Permettre Réservation en Ligne", default=True
    )
    booking_advance_days = fields.Integer("Jours d'Avance Réservation", default=7)
    average_rating = fields.Float("Note Moyenne", compute="_compute_average_rating")
    
    # CHAMP MANQUANT AJOUTÉ
    allow_priority_selection = fields.Boolean(
        "Permettre Sélection de Priorité", 
        default=False,
        help="Permet aux clients de choisir la priorité de leur ticket"
    )

    # Champs pour gestion avancée
    break_time_start = fields.Float("Début Pause")
    break_time_end = fields.Float("Fin Pause")
    lunch_break_start = fields.Float("Début Déjeuner")
    lunch_break_end = fields.Float("Fin Déjeuner")

    def action_generate_quick_ticket(self):
        """Générer rapidement un ticket sans dialogue - Version améliorée"""
        self.ensure_one()

        # Vérifications préliminaires
        if not self.is_open:
            raise UserError(_("Le service '%s' est actuellement fermé") % self.name)

        if not self.is_service_available():
            raise UserError(
                _("Le service '%s' n'est pas disponible à cette heure") % self.name
            )

        if self.total_tickets_today >= self.max_tickets_per_day:
            raise UserError(
                _("Nombre maximum de tickets atteint pour aujourd'hui (%s)")
                % self.max_tickets_per_day
            )

        try:
            # Générer le ticket
            self.current_ticket_number += 1
            ticket = self.env["queue.ticket"].create(
                {
                    "service_id": self.id,
                    "ticket_number": self.current_ticket_number,
                    "customer_name": self.env.context.get("customer_name", ""),
                    "customer_phone": self.env.context.get("customer_phone", ""),
                    "customer_email": self.env.context.get("customer_email", ""),
                    "priority": self.env.context.get("priority", "normal"),
                }
            )

            # Log de l'activité
            self.message_post(
                body=_("Nouveau ticket généré: #%s") % ticket.ticket_number,
                subtype_xmlid="mail.mt_note",
            )

            # Retourner une action client pour afficher le ticket
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Ticket Généré"),
                    "message": _(
                        "Ticket #%03d créé avec succès pour %s\nTemps d'attente estimé: %d minutes"
                    )
                    % (ticket.ticket_number, self.name, ticket.estimated_wait_time),
                    "type": "success",
                    "sticky": True,
                    "fadeout": 5000,
                },
                "next": {
                    "type": "ir.actions.act_window",
                    "res_model": "queue.ticket",
                    "res_id": ticket.id,
                    "view_mode": "form",
                    "view_type": "form",
                    "target": "new",
                },
            }

        except Exception as e:
            _logger.error(f"Erreur lors de la génération du ticket: {e}")
            raise UserError(_("Erreur lors de la génération du ticket: %s") % str(e))

    def action_generate_ticket_with_details(self):
        """Ouvrir un wizard pour créer un ticket avec détails client"""
        return {
            "type": "ir.actions.act_window",
            "name": _("Nouveau Ticket"),
            "res_model": "queue.ticket.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_service_id": self.id,
                "default_ticket_number": self.next_ticket_number,
            },
        }

    def action_call_next_ticket(self):
        """Appeler le prochain ticket en attente"""
        self.ensure_one()

        next_ticket = self.waiting_ticket_ids.sorted("ticket_number")[:1]
        if not next_ticket:
            raise UserError(_("Aucun ticket en attente pour ce service"))

        result = next_ticket.action_call_next()

        # Notification
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Ticket Appelé"),
                "message": _("Ticket #%03d appelé") % next_ticket.ticket_number,
                "type": "info",
                "sticky": False,
            },
        }

    def action_view_tickets(self):
        """Voir tous les tickets du service"""
        return {
            "type": "ir.actions.act_window",
            "name": _("Tickets - %s") % self.name,
            "res_model": "queue.ticket",
            "view_mode": "tree,form",
            "domain": [("service_id", "=", self.id)],
            "context": {"default_service_id": self.id},
        }

    def action_view_waiting_tickets(self):
        """Voir les tickets en attente"""
        return {
            "type": "ir.actions.act_window",
            "name": _("Tickets en Attente - %s") % self.name,
            "res_model": "queue.ticket",
            "view_mode": "tree,form",
            "domain": [("service_id", "=", self.id), ("state", "=", "waiting")],
            "context": {"default_service_id": self.id},
        }

    @api.model
    def reset_daily_counters(self):
        """Réinitialiser les compteurs quotidiens (à appeler via cron)"""
        services = self.search([("active", "=", True)])
        for service in services:
            service.current_ticket_number = 0
        _logger.info(
            "Compteurs quotidiens réinitialisés pour %d services", len(services)
        )

    @api.constrains("working_hours_start", "working_hours_end")
    def _check_working_hours(self):
        """Vérifier la cohérence des heures de travail"""
        for service in self:
            if service.working_hours_start >= service.working_hours_end:
                raise ValidationError(
                    _(
                        "L'heure de fermeture doit être postérieure à l'heure d'ouverture"
                    )
                )

    @api.constrains("break_time_start", "break_time_end")
    def _check_break_times(self):
        """Vérifier la cohérence des heures de pause"""
        for service in self:
            if service.break_time_start and service.break_time_end:
                if service.break_time_start >= service.break_time_end:
                    raise ValidationError(
                        _("L'heure de fin de pause doit être postérieure au début")
                    )

                # Vérifier que la pause est dans les heures d'ouverture
                if (
                    service.break_time_start < service.working_hours_start
                    or service.break_time_end > service.working_hours_end
                ):
                    raise ValidationError(
                        _(
                            "Les heures de pause doivent être dans les heures d'ouverture"
                        )
                    )

    def get_queue_status(self):
        """Obtenir le statut complet de la file d'attente"""
        self.ensure_one()

        waiting_tickets = self.waiting_ticket_ids.sorted("ticket_number")
        serving_tickets = self.ticket_ids.filtered(lambda t: t.state == "serving")

        return {
            "service_name": self.name,
            "is_open": self.is_open,
            "current_ticket": self.current_ticket_number,
            "waiting_count": len(waiting_tickets),
            "estimated_wait": (
                sum(t.estimated_wait_time for t in waiting_tickets)
                / len(waiting_tickets)
                if waiting_tickets
                else 0
            ),
            "serving_tickets": [
                {
                    "id": t.id,
                    "number": t.ticket_number,
                    "customer_name": t.customer_name,
                    "start_time": t.called_time,
                }
                for t in serving_tickets
            ],
            "next_tickets": [
                {
                    "id": t.id,
                    "number": t.ticket_number,
                    "customer_name": t.customer_name,
                    "wait_time": t.estimated_wait_time,
                    "priority": t.priority,
                }
                for t in waiting_tickets[:10]
            ],  # Top 10
        }

    @api.depends("ticket_ids.rating")
    def _compute_average_rating(self):
        """Calculer la note moyenne du service"""
        for service in self:
            ratings = service.ticket_ids.filtered("rating").mapped("rating")
            if ratings:
                service.average_rating = sum(int(r) for r in ratings) / len(ratings)
            else:
                service.average_rating = 0.0

    @api.depends("current_ticket_number")
    def _compute_next_ticket(self):
        for service in self:
            service.next_ticket_number = service.current_ticket_number + 1

    @api.depends("ticket_ids")
    def _compute_stats(self):
        for service in self:
            today = fields.Date.today()
            tickets_today = service.ticket_ids.filtered(
                lambda t: t.create_date.date() == today
            )
            service.total_tickets_today = len(tickets_today)
            service.waiting_count = len(service.waiting_ticket_ids)

            # Calcul temps d'attente moyen
            served_tickets = tickets_today.filtered(lambda t: t.state == "served")
            if served_tickets:
                total_wait_time = sum(t.waiting_time for t in served_tickets)
                service.avg_waiting_time = total_wait_time / len(served_tickets)
            else:
                service.avg_waiting_time = 0.0

    def generate_ticket(self):
        """Générer un nouveau ticket pour ce service (ancienne méthode conservée)"""
        if not self.is_open:
            raise UserError(_("Le service est actuellement fermé"))

        if self.total_tickets_today >= self.max_tickets_per_day:
            raise UserError(_("Nombre maximum de tickets atteint pour aujourd'hui"))

        self.current_ticket_number += 1
        ticket = self.env["queue.ticket"].create(
            {
                "service_id": self.id,
                "ticket_number": self.current_ticket_number,
                "customer_phone": self.env.context.get("customer_phone", ""),
                "customer_email": self.env.context.get("customer_email", ""),
            }
        )
        return ticket

    def is_service_available(self, check_time=None):
        """Vérifier si le service est disponible à une heure donnée"""
        if not check_time:
            check_time = fields.Datetime.now().time()

        hour_float = check_time.hour + check_time.minute / 60.0

        # Vérifier les heures d'ouverture
        if hour_float < self.working_hours_start or hour_float > self.working_hours_end:
            return False

        # Vérifier les pauses
        if (
            self.break_time_start
            and self.break_time_end
            and self.break_time_start <= hour_float <= self.break_time_end
        ):
            return False

        if (
            self.lunch_break_start
            and self.lunch_break_end
            and self.lunch_break_start <= hour_float <= self.lunch_break_end
        ):
            return False

        return self.is_open

    def get_next_available_slot(self):
        """Obtenir le prochain créneau disponible"""
        now = fields.Datetime.now()
        current_queue_length = len(self.waiting_ticket_ids)

        # Calculer le temps d'attente basé sur la file actuelle
        estimated_wait_minutes = current_queue_length * self.estimated_service_time
        next_available = now + timedelta(minutes=estimated_wait_minutes)

        return next_available

    @api.model
    def get_dashboard_data(self):
        """Données pour le tableau de bord"""
        services = self.search([("active", "=", True)])

        # Calculs globaux
        total_waiting = sum(s.waiting_count for s in services)
        total_served_today = sum(s.total_tickets_today for s in services)
        active_services = len(services.filtered("is_open"))

        # Temps d'attente moyen global
        avg_wait_times = [
            s.avg_waiting_time for s in services if s.avg_waiting_time > 0
        ]
        global_avg_wait = (
            sum(avg_wait_times) / len(avg_wait_times) if avg_wait_times else 0
        )

        # Données des services
        services_data = []
        for service in services:
            next_tickets = service.waiting_ticket_ids.sorted("ticket_number")[:5]
            services_data.append(
                {
                    "id": service.id,
                    "name": service.name,
                    "is_open": service.is_open,
                    "waiting_count": service.waiting_count,
                    "current_ticket": service.current_ticket_number,
                    "next_tickets": [
                        {
                            "id": t.id,
                            "number": t.ticket_number,
                            "customer_name": t.customer_name,
                            "state": t.state,
                            "priority": t.priority,
                            "estimated_wait": t.estimated_wait_time,
                        }
                        for t in next_tickets
                    ],
                }
            )

        return {
            "total_waiting": total_waiting,
            "total_served_today": total_served_today,
            "avg_wait_time": round(global_avg_wait, 1),
            "active_services": active_services,
            "services": services_data,
        }

    def toggle_service_status(self):
        """Basculer l'état ouvert/fermé du service"""
        self.is_open = not self.is_open
        return True

    @api.model
    def get_service_statistics(self, date_from=None, date_to=None):
        """Obtenir les statistiques d'un service sur une période"""
        domain = [("service_id", "in", self.ids)]

        if date_from:
            domain.append(("create_date", ">=", date_from))
        if date_to:
            domain.append(("create_date", "<=", date_to))

        tickets = self.env["queue.ticket"].search(domain)

        stats = {}
        for service in self:
            service_tickets = tickets.filtered(lambda t: t.service_id.id == service.id)
            served_tickets = service_tickets.filtered(lambda t: t.state == "served")

            stats[service.id] = {
                "total_tickets": len(service_tickets),
                "served_tickets": len(served_tickets),
                "cancelled_tickets": len(
                    service_tickets.filtered(lambda t: t.state == "cancelled")
                ),
                "no_show_tickets": len(
                    service_tickets.filtered(lambda t: t.state == "no_show")
                ),
                "avg_waiting_time": (
                    sum(t.waiting_time for t in served_tickets) / len(served_tickets)
                    if served_tickets
                    else 0
                ),
                "avg_service_time": (
                    sum(t.service_time for t in served_tickets) / len(served_tickets)
                    if served_tickets
                    else 0
                ),
                "satisfaction_rate": (
                    len(served_tickets) / len(service_tickets) * 100
                    if service_tickets
                    else 0
                ),
            }

        return stats