# models/queue_service.py
from odoo import models, fields, api, _
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta, time
import pytz
import json
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
        "Tickets aujourd'hui", compute="_compute_stats", store=True
    )
    waiting_count = fields.Integer("En attente", compute="_compute_stats", store=True)
    avg_waiting_time = fields.Float(
        "Temps d'attente moyen (min)", compute="_compute_stats", store=True
    )

    # Nouveaux champs pour amélioration
    allow_online_booking = fields.Boolean(
        "Permettre Réservation en Ligne", default=True
    )
    booking_advance_days = fields.Integer("Jours d'Avance Réservation", default=7)
    average_rating = fields.Float(
        "Note Moyenne", compute="_compute_average_rating", store=True
    )

    # CHAMP MANQUANT AJOUTÉ
    allow_priority_selection = fields.Boolean(
        "Permettre Sélection de Priorité",
        default=False,
        help="Permet aux clients de choisir la priorité de leur ticket",
    )

    # Champs pour gestion avancée
    break_time_start = fields.Float("Début Pause")
    break_time_end = fields.Float("Fin Pause")
    lunch_break_start = fields.Float("Début Déjeuner")
    lunch_break_end = fields.Float("Fin Déjeuner")
    # Nouveaux champs pour les statistiques d'annulation
    cancellation_rate = fields.Float(
        "Taux d'annulation (%)", compute="_compute_cancellation_stats", store=True
    )
    total_cancelled_today = fields.Integer(
        "Annulations aujourd'hui", compute="_compute_cancellation_stats", store=True
    )
    avg_time_before_cancellation = fields.Float(
        "Temps moyen avant annulation (min)",
        compute="_compute_cancellation_stats",
        store=True,
    )

    # Nouveaux champs pour la référence des tickets
    ticket_prefix = fields.Char(
        "Préfixe des tickets",
        default="QUE",
        help="Préfixe utilisé pour les références de tickets",
    )
    ticket_sequence = fields.Integer(
        "Séquence des tickets",
        default=0,
        help="Compteur séquentiel pour les numéros de ticket",
    )

    @api.model
    def cleanup_old_statistics(self):
        cutoff_date = datetime.now() - timedelta(days=30)
        old_tickets = self.env["queue.ticket"].search(
            [
                ("created_time", "<", cutoff_date),
                ("state", "in", ["served", "cancelled", "no_show"]),
            ]
        )
        old_tickets.write({"active": False})
        _logger.info(f"Archivé {len(old_tickets)} anciens tickets")

    @api.depends("ticket_ids", "ticket_ids.state", "ticket_ids.cancelled_time")
    def _compute_cancellation_stats(self):
        """Calculer les statistiques d'annulation"""
        for service in self:
            today = fields.Date.today()

            # Tickets d'aujourd'hui
            today_tickets = service.ticket_ids.filtered(
                lambda t: t.created_time and t.created_time.date() == today
            )

            total_today = len(today_tickets)
            cancelled_today = today_tickets.filtered(lambda t: t.state == "cancelled")

            service.total_cancelled_today = len(cancelled_today)

            if total_today > 0:
                service.cancellation_rate = (len(cancelled_today) / total_today) * 100
            else:
                service.cancellation_rate = 0.0

            # Temps moyen avant annulation
            if cancelled_today:
                total_wait_time = sum(
                    [
                        (t.cancelled_time - t.created_time).total_seconds() / 60
                        for t in cancelled_today
                        if t.cancelled_time and t.created_time
                    ]
                )
                service.avg_time_before_cancellation = total_wait_time / len(
                    cancelled_today
                )
            else:
                service.avg_time_before_cancellation = 0.0

    def _update_cancellation_stats(self):
        """Méthode appelée après chaque annulation pour mise à jour rapide"""
        self._compute_cancellation_stats()

        # Alerte si taux d'annulation trop élevé
        if self.cancellation_rate > 30:  # Plus de 30% d'annulation
            self._send_cancellation_alert()

    def _send_cancellation_alert(self):
        """Envoyer une alerte en cas de taux d'annulation élevé"""
        try:
            # Notifier les administrateurs
            admin_users = self.env.ref("queue_management.group_queue_manager").users

            for user in admin_users:
                self.env["mail.mail"].sudo().create(
                    {
                        "subject": f"Alerte: Taux d'annulation élevé - {self.name}",
                        "body_html": f"""
                        <h3>Alerte Taux d'Annulation</h3>
                        <p>Le service <strong>{self.name}</strong> présente un taux d'annulation élevé:</p>
                        <ul>
                            <li>Taux d'annulation: <strong>{self.cancellation_rate:.1f}%</strong></li>
                            <li>Annulations aujourd'hui: <strong>{self.total_cancelled_today}</strong></li>
                            <li>Temps moyen avant annulation: <strong>{self.avg_time_before_cancellation:.1f} min</strong></li>
                        </ul>
                        <p>Veuillez vérifier la configuration du service et les temps d'attente.</p>
                    """,
                        "email_to": user.email,
                        "auto_delete": True,
                    }
                ).send()

        except Exception as e:
            _logger.error(f"Erreur envoi alerte annulation: {e}")

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
            # Incrémenter le compteur de tickets
            self.current_ticket_number += 1

            # Préparer les valeurs avec le nouveau système de référence
            vals = {
                "service_id": self.id,
                "ticket_number": self.current_ticket_number,
                "customer_name": self.env.context.get("customer_name", ""),
                "customer_phone": self.env.context.get("customer_phone", ""),
                "customer_email": self.env.context.get("customer_email", ""),
                "priority": self.env.context.get("priority", "normal"),
            }

            # Créer le ticket avec les références automatiques
            ticket = self.env["queue.ticket"].create(vals)

            # Log de l'activité
            self.message_post(
                body=_("Nouveau ticket généré: %s") % ticket.ticket_reference,
                subtype_xmlid="mail.mt_note",
            )

            # Retourner la nouvelle référence dans la notification
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Ticket Généré"),
                    "message": _(
                        "Ticket %s créé avec succès pour %s\nTemps d'attente estimé: %d minutes"
                    )
                    % (ticket.ticket_reference, self.name, ticket.estimated_wait_time),
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

    # Ajouter une méthode pour trouver un ticket par référence
    def find_ticket_by_reference(self, reference):
        """Trouver un ticket par sa référence"""
        return self.env["queue.ticket"].search(
            [
                ("service_id", "=", self.id),
                "|",
                ("ticket_reference", "=", reference),
                ("short_reference", "=", reference),
            ],
            limit=1,
        )

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

    # Ajouter une méthode pour annuler un ticket par référence
    def cancel_ticket_by_reference(self, reference, reason=None):
        """Annuler un ticket par sa référence"""
        self.ensure_one()
        ticket = self.find_ticket_by_reference(reference)
        if not ticket:
            raise UserError(_("Ticket non trouvé avec la référence %s") % reference)

        return ticket.action_cancel_ticket_v2(
            reason=reason or _("Annulé par l'administration"), cancellation_type="agent"
        )

    # 2. CORRECTION de la méthode _compute_stats dans queue_service.py
    # Mettre à jour les statistiques pour inclure les nouvelles métriques
    @api.depends("ticket_ids", "ticket_ids.state", "ticket_ids.created_time")
    def _compute_stats(self):
        """Version améliorée avec les nouveaux champs"""
        for service in self:
            try:
                today = fields.Date.today()
                tomorrow = today + timedelta(days=1)
                today_start = fields.Datetime.to_string(
                    datetime.combine(today, time.min)
                )
                today_end = fields.Datetime.to_string(
                    datetime.combine(tomorrow, time.min)
                )

                # Tickets d'aujourd'hui avec les nouveaux champs
                today_tickets = self.env["queue.ticket"].search(
                    [
                        ("service_id", "=", service.id),
                        ("created_time", ">=", today_start),
                        ("created_time", "<", today_end),
                    ]
                )

                # Tickets en attente
                waiting_tickets = self.env["queue.ticket"].search(
                    [("service_id", "=", service.id), ("state", "=", "waiting")]
                )

                # Calculs de base
                service.total_tickets_today = len(today_tickets)
                service.waiting_count = len(waiting_tickets)

                # Temps d'attente moyen (uniquement pour les tickets servis)
                served_tickets_with_wait = today_tickets.filtered(
                    lambda t: t.state == "served" and t.waiting_time > 0
                )
                if served_tickets_with_wait:
                    total_wait_time = sum(
                        t.waiting_time for t in served_tickets_with_wait
                    )
                    service.avg_waiting_time = total_wait_time / len(
                        served_tickets_with_wait
                    )
                else:
                    service.avg_waiting_time = 0.0

                # Statistiques d'annulation
                cancelled_today = today_tickets.filtered(
                    lambda t: t.state == "cancelled"
                )
                service.total_cancelled_today = len(cancelled_today)

                if today_tickets:
                    service.cancellation_rate = (
                        len(cancelled_today) / len(today_tickets)
                    ) * 100
                else:
                    service.cancellation_rate = 0.0

            except Exception as e:
                _logger.error(f"Erreur calcul stats service {service.id}: {e}")
                service.total_tickets_today = 0
                service.waiting_count = 0
                service.avg_waiting_time = 0.0
                service.total_cancelled_today = 0
                service.cancellation_rate = 0.0

    def _get_tickets_safely(self, domain):
        """Récupère les tickets avec gestion d'erreurs"""
        try:
            return self.env["queue.ticket"].search(domain)
        except Exception as e:
            _logger.warning(f"Erreur lors de la récupération des tickets: {e}")
            return self.env["queue.ticket"]

    def _calculate_avg_waiting_time(self, tickets):
        """Calcule le temps d'attente moyen de manière robuste"""
        if not tickets:
            return 0.0

        try:
            total_waiting_time = 0.0
            valid_tickets = 0

            for ticket in tickets:
                if ticket.waiting_time and ticket.waiting_time > 0:
                    total_waiting_time += ticket.waiting_time
                    valid_tickets += 1

            return total_waiting_time / valid_tickets if valid_tickets > 0 else 0.0

        except Exception as e:
            _logger.warning(f"Erreur calcul temps d'attente moyen: {e}")
            return 0.0

    def _calculate_average_rating(self, tickets):
        """Calcule la note moyenne de manière robuste"""
        if not tickets:
            return 0.0

        try:
            ratings = []
            for ticket in tickets:
                if ticket.rating and ticket.rating > 0:
                    ratings.append(ticket.rating)

            return sum(ratings) / len(ratings) if ratings else 0.0

        except Exception as e:
            _logger.warning(f"Erreur calcul note moyenne: {e}")
            return 0.0

    def _set_default_stats(self):
        """Définit les statistiques par défaut en cas d'erreur"""
        self.total_tickets_today = 0
        self.waiting_count = 0
        self.avg_waiting_time = 0.0
        self.average_rating = 0.0

    def _log_computation_error(self, error, service):
        """Log les erreurs de calcul pour debug"""
        _logger.error(
            f"Erreur calcul statistiques pour service {service.name} (ID: {service.id}): {error}"
        )

    # Méthode alternative plus simple sans timezone
    @api.depends("ticket_ids", "ticket_ids.state", "ticket_ids.created_time")
    def _compute_stats_simple(self):
        """Version simplifiée du calcul des statistiques"""
        for service in self:
            try:
                # Utilisation de la date courante sans gestion timezone complexe
                today_start = fields.Datetime.today()
                today_end = today_start + timedelta(days=1)

                # Domaines simplifiés
                today_domain = [
                    ("service_id", "=", service.id),
                    ("created_time", ">=", today_start),
                    ("created_time", "<", today_end),
                ]

                waiting_domain = [
                    ("service_id", "=", service.id),
                    ("state", "=", "waiting"),
                ]

                # Comptage direct
                service.total_tickets_today = self.env["queue.ticket"].search_count(
                    today_domain
                )
                service.waiting_count = self.env["queue.ticket"].search_count(
                    waiting_domain
                )

                # Calculs moyens avec read_group pour performance
                avg_data = self.env["queue.ticket"].read_group(
                    domain=today_domain + [("waiting_time", ">", 0)],
                    fields=["waiting_time:avg"],
                    groupby=[],
                )
                service.avg_waiting_time = (
                    avg_data[0]["waiting_time"] if avg_data else 0.0
                )

                rating_data = self.env["queue.ticket"].read_group(
                    domain=today_domain + [("rating", ">", 0)],
                    fields=["rating:avg"],
                    groupby=[],
                )
                service.average_rating = (
                    rating_data[0]["rating"] if rating_data else 0.0
                )

            except Exception as e:
                _logger.error(f"Erreur calcul stats service {service.id}: {e}")
                service._set_default_stats()

    # Méthode pour forcer la recalcul des statistiques
    def refresh_stats(self):
        """Force le recalcul des statistiques"""
        try:
            self._compute_stats()
            return True
        except Exception as e:
            _logger.error(f"Erreur lors du refresh des stats: {e}")
            return False

    # Méthode pour obtenir les stats sous forme de dictionnaire
    def get_stats_dict(self):
        """Retourne les statistiques sous forme de dictionnaire"""
        return {
            "total_tickets_today": self.total_tickets_today or 0,
            "waiting_count": self.waiting_count or 0,
            "avg_waiting_time": round(self.avg_waiting_time or 0, 1),
            "average_rating": round(self.average_rating or 0, 1),
            "current_ticket_number": self.current_ticket_number or 0,
            "is_open": self.is_open,
            "service_name": self.name,
        }

    def get_detailed_stats(self, period_start=None, period_end=None):
        """Obtenir des statistiques détaillées pour une période donnée"""
        self.ensure_one()

        if not period_start:
            period_start = fields.Date.today()
        if not period_end:
            period_end = fields.Date.today()

        # Domain pour la période
        domain = [
            ("service_id", "=", self.id),
            ("created_time", ">=", period_start),
            ("created_time", "<=", period_end + timedelta(days=1)),
        ]

        tickets = self.env["queue.ticket"].search(domain)

        if not tickets:
            return {
                "total_tickets": 0,
                "served_tickets": 0,
                "cancelled_tickets": 0,
                "no_show_tickets": 0,
                "avg_waiting_time": 0,
                "avg_service_time": 0,
                "peak_hours": [],
                "satisfaction_rate": 0,
                "efficiency_rate": 0,
            }

        # Groupement par état
        tickets_by_state = {}
        for state in ["waiting", "called", "serving", "served", "cancelled", "no_show"]:
            tickets_by_state[state] = tickets.filtered(lambda t: t.state == state)

        served_tickets = tickets_by_state["served"]

        # Calculs statistiques
        total_tickets = len(tickets)
        served_count = len(served_tickets)

        # Temps d'attente moyen (uniquement pour les tickets servis)
        avg_waiting_time = 0
        if served_tickets:
            valid_wait_times = [
                t.waiting_time for t in served_tickets if t.waiting_time > 0
            ]
            avg_waiting_time = (
                sum(valid_wait_times) / len(valid_wait_times) if valid_wait_times else 0
            )

        # Temps de service moyen
        avg_service_time = 0
        if served_tickets:
            valid_service_times = [
                t.service_time for t in served_tickets if t.service_time > 0
            ]
            avg_service_time = (
                sum(valid_service_times) / len(valid_service_times)
                if valid_service_times
                else 0
            )

        # Heures de pointe (analyse par heure)
        hourly_distribution = {}
        for ticket in tickets:
            if ticket.created_time:
                hour = ticket.created_time.hour
                hourly_distribution[hour] = hourly_distribution.get(hour, 0) + 1

        # Top 3 des heures les plus chargées
        peak_hours = sorted(
            hourly_distribution.items(), key=lambda x: x[1], reverse=True
        )[:3]
        peak_hours = [{"hour": f"{h:02d}:00", "count": c} for h, c in peak_hours]

        # Taux de satisfaction (basé sur les évaluations)
        rated_tickets = served_tickets.filtered("rating")
        satisfaction_rate = 0
        if rated_tickets:
            total_rating = sum(int(t.rating) for t in rated_tickets)
            satisfaction_rate = (
                total_rating / (len(rated_tickets) * 5)
            ) * 100  # Sur 5 étoiles

        # Taux d'efficacité (tickets servis / tickets totaux)
        efficiency_rate = (
            (served_count / total_tickets * 100) if total_tickets > 0 else 0
        )

        return {
            "total_tickets": total_tickets,
            "served_tickets": served_count,
            "cancelled_tickets": len(tickets_by_state["cancelled"]),
            "no_show_tickets": len(tickets_by_state["no_show"]),
            "waiting_tickets": len(tickets_by_state["waiting"]),
            "serving_tickets": len(tickets_by_state["serving"]),
            "avg_waiting_time": round(avg_waiting_time, 2),
            "avg_service_time": round(avg_service_time, 2),
            "peak_hours": peak_hours,
            "satisfaction_rate": round(satisfaction_rate, 1),
            "efficiency_rate": round(efficiency_rate, 1),
            "hourly_distribution": hourly_distribution,
        }

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

    # Dans le modèle queue.service.py
    # 4. CORRECTION de get_dashboard_data - Version simplifiée et robuste
    @api.model
    def get_dashboard_data(self):
        """Version corrigée avec calcul de performance"""
        try:
            # 1. Récupération des services
            services = self.search([("active", "=", True)])
            if not services:
                return self._get_empty_dashboard_data()

            # 2. Date d'aujourd'hui
            today = fields.Date.today()
            tomorrow = today + timedelta(days=1)
            today_start = fields.Datetime.to_string(datetime.combine(today, time.min))
            today_end = fields.Datetime.to_string(datetime.combine(tomorrow, time.min))

            # 3. Récupération des tickets
            all_tickets_today = self.env["queue.ticket"].search(
                [
                    ("created_time", ">=", today_start),
                    ("created_time", "<", today_end),
                    ("service_id", "in", services.ids),
                ]
            )

            waiting_tickets = self.env["queue.ticket"].search(
                [("state", "=", "waiting"), ("service_id", "in", services.ids)]
            )

            serving_tickets = self.env["queue.ticket"].search(
                [("state", "=", "serving"), ("service_id", "in", services.ids)]
            )

            # 4. Construction des données par service
            services_data = []
            total_waiting = 0
            total_serving = 0
            total_served = 0
            all_wait_times = []

            for service in services:
                # Filtres par service
                service_tickets_today = all_tickets_today.filtered(
                    lambda t: t.service_id.id == service.id
                )
                service_waiting = waiting_tickets.filtered(
                    lambda t: t.service_id.id == service.id
                )
                service_serving = serving_tickets.filtered(
                    lambda t: t.service_id.id == service.id
                )
                service_served = service_tickets_today.filtered(
                    lambda t: t.state == "served"
                )

                # Comptages
                waiting_count = len(service_waiting)
                serving_count = len(service_serving)
                served_count = len(service_served)

                # Temps d'attente moyen
                served_with_wait = service_served.filtered(
                    lambda t: t.waiting_time and t.waiting_time > 0
                )
                avg_wait = 0.0
                if served_with_wait:
                    total_wait = sum(t.waiting_time for t in served_with_wait)
                    avg_wait = total_wait / len(served_with_wait)
                    all_wait_times.append(avg_wait)

                # CALCUL DE LA CAPACITÉ (NOUVEAU)
                capacity_percentage = 0
                if service.max_tickets_per_day > 0:
                    capacity_percentage = min(
                        (len(service_tickets_today) / service.max_tickets_per_day)
                        * 100,
                        100,
                    )

                # Mise à jour des totaux
                total_waiting += waiting_count
                total_serving += serving_count
                total_served += served_count

                # Données du service
                service_data = {
                    "id": service.id,
                    "name": service.name,
                    "is_open": service.is_open,
                    "waiting_count": waiting_count,
                    "serving_count": serving_count,
                    "served_count": served_count,
                    "total_tickets_today": len(service_tickets_today),
                    "current_ticket": service.current_ticket_number or 0,
                    "avg_waiting_time": round(avg_wait, 1),
                    "estimated_service_time": service.estimated_service_time or 15,
                    "capacity_percentage": round(capacity_percentage, 1),  # NOUVEAU
                }
                services_data.append(service_data)

            # 5. Statistiques globales
            global_avg_wait = (
                sum(all_wait_times) / len(all_wait_times) if all_wait_times else 0.0
            )
            total_tickets = len(all_tickets_today)

            stats = {
                "total_tickets": total_tickets,
                "completed_tickets": total_served,
                "waiting_tickets": total_waiting,
                "serving_tickets": total_serving,
                "cancelled_tickets": len(
                    all_tickets_today.filtered(lambda t: t.state == "cancelled")
                ),
                "no_show_tickets": len(
                    all_tickets_today.filtered(lambda t: t.state == "no_show")
                ),
                "average_wait_time": round(global_avg_wait, 1),
                "completion_rate": (
                    round((total_served / total_tickets * 100), 1)
                    if total_tickets > 0
                    else 0
                ),
                "active_services": len(services.filtered("is_open")),
                "total_services": len(services),
            }

            # 6. Construction des données des tickets (simplifiée)
            waiting_tickets_data = []
            for ticket in waiting_tickets.sorted(
                lambda t: (t.service_id.id, t.ticket_number)
            ):
                waiting_tickets_data.append(
                    {
                        "id": ticket.id,
                        "number": ticket.ticket_number,
                        "service_name": ticket.service_id.name,
                        "customer_name": ticket.customer_name or "Client Anonyme",
                        "created_time": (
                            ticket.created_time.strftime("%H:%M")
                            if ticket.created_time
                            else ""
                        ),
                        "estimated_wait": round(
                            getattr(ticket, "estimated_wait_time", 0), 1
                        ),
                        "priority": getattr(ticket, "priority", "normal"),
                    }
                )

            serving_tickets_data = []
            for ticket in serving_tickets:
                serving_tickets_data.append(
                    {
                        "id": ticket.id,
                        "number": ticket.ticket_number,
                        "service_name": ticket.service_id.name,
                        "customer_name": ticket.customer_name or "Client Anonyme",
                        "agent_name": getattr(ticket, "agent_name", "Agent"),
                        "service_duration": round(
                            getattr(ticket, "service_duration", 0), 1
                        ),
                    }
                )

            return {
                "services": services_data,
                "waiting_tickets": waiting_tickets_data,
                "serving_tickets": serving_tickets_data,
                "stats": stats,
                "last_update": fields.Datetime.now().strftime("%H:%M:%S"),
            }

        except Exception as e:
            _logger.error(f"Erreur dans get_dashboard_data: {e}")
            return self._get_error_dashboard_data(str(e))

    # 5. AJOUT d'une méthode pour forcer la mise à jour des statistiques
    def force_refresh_stats(self):
        """Force la mise à jour des statistiques - À appeler depuis l'interface"""
        try:
            # Forcer le recalcul des temps d'attente pour tous les tickets
            tickets = self.env["queue.ticket"].search([("service_id", "in", self.ids)])
            tickets._compute_waiting_time()

            # Forcer le recalcul des statistiques des services
            self._compute_stats()

            # Invalider le cache
            self.invalidate_cache()

            return True
        except Exception as e:
            _logger.error(f"Erreur refresh stats: {e}")
            return False

    # 6. MÉTHODE DE DÉBOGAGE pour identifier les problèmes
    @api.model
    def debug_waiting_times(self):
        """Méthode de debug pour analyser les temps d'attente"""
        services = self.search([("active", "=", True)])
        debug_info = {}

        for service in services:
            tickets = service.ticket_ids.filtered(
                lambda t: t.created_time.date() == fields.Date.today()
            )

            debug_info[service.name] = {
                "total_tickets": len(tickets),
                "tickets_with_waiting_time": len(
                    tickets.filtered(lambda t: t.waiting_time > 0)
                ),
                "served_tickets": len(tickets.filtered(lambda t: t.state == "served")),
                "avg_waiting_time_computed": service.avg_waiting_time,
                "ticket_details": [
                    {
                        "number": t.ticket_number,
                        "state": t.state,
                        "waiting_time": t.waiting_time,
                        "created": (
                            t.created_time.strftime("%H:%M")
                            if t.created_time
                            else "N/A"
                        ),
                        "called": (
                            t.called_time.strftime("%H:%M") if t.called_time else "N/A"
                        ),
                    }
                    for t in tickets[:5]  # 5 premiers tickets pour debug
                ],
            }

        return debug_info

    def _get_tickets_safely(self, domain, description="tickets"):
        """Récupération sécurisée des tickets avec gestion d'erreurs"""
        try:
            tickets = self.env["queue.ticket"].search(domain)
            _logger.debug(f"Récupération réussie: {len(tickets)} {description}")
            return tickets
        except Exception as e:
            _logger.error(f"Erreur récupération {description}: {e}")
            return self.env["queue.ticket"]

    def _filter_tickets_by_service(self, tickets, service_id):
        """Filtrage sécurisé des tickets par service"""
        try:
            if not tickets:
                return self.env["queue.ticket"]

            filtered_tickets = tickets.filtered(
                lambda t: hasattr(t, "service_id") and t.service_id.id == service_id
            )
            return filtered_tickets
        except Exception as e:
            _logger.warning(f"Erreur filtrage tickets service {service_id}: {e}")
            return self.env["queue.ticket"]

    def _calculate_service_avg_wait_time(self, served_tickets):
        """Calcul robuste du temps d'attente moyen d'un service"""
        try:
            if not served_tickets:
                return 0.0

            valid_wait_times = []
            for ticket in served_tickets:
                try:
                    if (
                        hasattr(ticket, "waiting_time")
                        and ticket.waiting_time
                        and ticket.waiting_time > 0
                    ):
                        wait_time = float(ticket.waiting_time)
                        if 0 < wait_time < 1440:  # Maximum 24h en minutes
                            valid_wait_times.append(wait_time)
                except (ValueError, TypeError) as e:
                    _logger.debug(
                        f"Temps d'attente invalide pour ticket {ticket.id}: {e}"
                    )
                    continue

            if valid_wait_times:
                return sum(valid_wait_times) / len(valid_wait_times)
            return 0.0

        except Exception as e:
            _logger.warning(f"Erreur calcul temps attente moyen: {e}")
            return 0.0

    def _validate_current_ticket_number(self, service, service_tickets):
        """Validation et correction du numéro de ticket actuel"""
        try:
            stored_number = service.current_ticket_number or 0

            if service_tickets:
                max_ticket_number = max(service_tickets.mapped("ticket_number") + [0])
                if stored_number != max_ticket_number:
                    _logger.info(
                        f"Correction numéro ticket service {service.id}: {stored_number} -> {max_ticket_number}"
                    )
                    # Correction automatique (optionnelle)
                    # service.sudo().current_ticket_number = max_ticket_number
                    return max_ticket_number

            return stored_number

        except Exception as e:
            _logger.warning(
                f"Erreur validation numéro ticket service {service.id}: {e}"
            )
            return service.current_ticket_number or 0

    def _check_service_availability(self, service):
        """Vérification de la disponibilité du service"""
        try:
            if not service.is_open:
                return False

            return (
                service.is_service_available()
                if hasattr(service, "is_service_available")
                else True
            )

        except Exception as e:
            _logger.warning(
                f"Erreur vérification disponibilité service {service.id}: {e}"
            )
            return bool(service.is_open)

    def _build_waiting_tickets_data(self, waiting_tickets):
        """Construction robuste des données des tickets en attente"""
        waiting_tickets_data = []

        try:
            # Tri sécurisé des tickets
            sorted_tickets = waiting_tickets.sorted(
                lambda t: (t.service_id.id, t.ticket_number)
            )

            # Grouper par service pour calculer les positions
            tickets_by_service = {}
            for ticket in sorted_tickets:
                service_id = ticket.service_id.id
                if service_id not in tickets_by_service:
                    tickets_by_service[service_id] = []
                tickets_by_service[service_id].append(ticket)

            # Construction des données
            for service_id, service_tickets in tickets_by_service.items():
                # Trier par priorité puis par numéro
                sorted_service_tickets = sorted(
                    service_tickets,
                    key=lambda t: (
                        self._get_priority_order(getattr(t, "priority", "normal")),
                        getattr(t, "ticket_number", 0),
                    ),
                    reverse=True,  # Priorité haute en premier
                )

                for position, ticket in enumerate(sorted_service_tickets, 1):
                    try:
                        ticket_data = {
                            "id": ticket.id,
                            "number": ticket.ticket_number or 0,
                            "service_id": service_id,
                            "service_name": ticket.service_id.name or "Service inconnu",
                            "customer_name": ticket.customer_name or "Client Anonyme",
                            "created_time": (
                                ticket.created_time.strftime("%H:%M")
                                if ticket.created_time
                                else ""
                            ),
                            "estimated_wait": round(
                                getattr(ticket, "estimated_wait_time", 0), 1
                            ),
                            "priority": getattr(ticket, "priority", "normal"),
                            "position_in_queue": position,
                            "waiting_duration": self._calculate_waiting_duration(
                                ticket
                            ),
                        }
                        waiting_tickets_data.append(ticket_data)

                    except Exception as ticket_error:
                        _logger.warning(
                            f"Erreur construction données ticket {ticket.id}: {ticket_error}"
                        )
                        continue

        except Exception as e:
            _logger.error(f"Erreur construction données tickets en attente: {e}")

        return waiting_tickets_data

    def _build_serving_tickets_data(self, serving_tickets):
        """Construction robuste des données des tickets en service"""
        serving_tickets_data = []

        try:
            sorted_tickets = serving_tickets.sorted(
                lambda t: (t.service_id.id, t.served_time or t.created_time)
            )

            for ticket in sorted_tickets:
                try:
                    # Calcul durée de service
                    service_duration = self._calculate_service_duration(ticket)

                    # Nom de l'agent
                    agent_name = self._get_agent_name(ticket)

                    ticket_data = {
                        "id": ticket.id,
                        "number": ticket.ticket_number or 0,
                        "service_id": ticket.service_id.id,
                        "service_name": ticket.service_id.name or "Service inconnu",
                        "customer_name": ticket.customer_name or "Client Anonyme",
                        "served_time": (
                            ticket.served_time.strftime("%H:%M")
                            if ticket.served_time
                            else ""
                        ),
                        "service_duration": round(service_duration, 1),
                        "agent_name": agent_name,
                        "progress_indicator": self._get_service_progress(
                            ticket, service_duration
                        ),
                    }
                    serving_tickets_data.append(ticket_data)

                except Exception as ticket_error:
                    _logger.warning(
                        f"Erreur construction données ticket en service {ticket.id}: {ticket_error}"
                    )
                    continue

        except Exception as e:
            _logger.error(f"Erreur construction données tickets en service: {e}")

        return serving_tickets_data

    def _calculate_waiting_duration(self, ticket):
        """Calcul de la durée d'attente actuelle"""
        try:
            if ticket.created_time:
                delta = fields.Datetime.now() - ticket.created_time
                minutes = delta.total_seconds() / 60
                return round(minutes, 1)
            return 0.0
        except Exception as e:
            _logger.debug(f"Erreur calcul durée attente ticket {ticket.id}: {e}")
            return 0.0

    def _calculate_service_duration(self, ticket):
        """Calcul de la durée de service actuelle"""
        try:
            if ticket.served_time:
                end_time = ticket.completed_time or fields.Datetime.now()
                delta = end_time - ticket.served_time
                return delta.total_seconds() / 60
            return 0.0
        except Exception as e:
            _logger.debug(f"Erreur calcul durée service ticket {ticket.id}: {e}")
            return 0.0

    def _get_agent_name(self, ticket):
        """Récupération du nom de l'agent"""
        try:
            if hasattr(ticket, "write_uid") and ticket.write_uid:
                return ticket.write_uid.name
            elif hasattr(ticket, "create_uid") and ticket.create_uid:
                return ticket.create_uid.name
            return "Agent Inconnu"
        except Exception as e:
            _logger.debug(f"Erreur récupération agent ticket {ticket.id}: {e}")
            return "Agent Inconnu"

    def _get_service_progress(self, ticket, duration):
        """Calcul du progrès du service"""
        try:
            estimated_duration = ticket.service_id.estimated_service_time or 15
            if estimated_duration > 0:
                progress = min((duration / estimated_duration) * 100, 100)
                return round(progress, 1)
            return 0.0
        except Exception:
            return 0.0

    def _calculate_global_statistics(
        self,
        all_tickets,
        served_today,
        waiting_global,
        serving_global,
        wait_times,
        services,
    ):
        """Calcul des statistiques globales avec protection d'erreurs"""
        try:
            cancelled_today = len(
                [t for t in all_tickets if getattr(t, "state", None) == "cancelled"]
            )
            no_show_today = len(
                [t for t in all_tickets if getattr(t, "state", None) == "no_show"]
            )

            total_tickets = len(all_tickets)
            global_avg_wait = sum(wait_times) / len(wait_times) if wait_times else 0

            completion_rate = (
                (served_today / total_tickets * 100) if total_tickets > 0 else 0
            )
            active_services = len([s for s in services if getattr(s, "is_open", False)])

            return {
                "total_tickets": total_tickets,
                "completed_tickets": served_today,
                "waiting_tickets": waiting_global,
                "serving_tickets": serving_global,
                "cancelled_tickets": cancelled_today,
                "no_show_tickets": no_show_today,
                "average_wait_time": round(global_avg_wait, 1),
                "completion_rate": round(completion_rate, 1),
                "active_services": active_services,
                "total_services": len(services),
                "efficiency_rate": (
                    round(completion_rate, 1) if completion_rate > 0 else 0
                ),
            }
        except Exception as e:
            _logger.error(f"Erreur calcul statistiques globales: {e}")
            return self._get_default_stats()

    def _get_default_service_data(self, service):
        """Données par défaut en cas d'erreur pour un service"""
        return {
            "id": service.id,
            "name": getattr(service, "name", "Service en erreur"),
            "is_open": False,
            "waiting_count": 0,
            "serving_count": 0,
            "served_count": 0,
            "total_tickets_today": 0,
            "current_ticket": 0,
            "avg_waiting_time": 0,
            "estimated_service_time": 15,
            "max_capacity": 100,
            "capacity_percentage": 0,
            "is_available": False,
            "error": True,
        }

    def _get_default_stats(self):
        """Statistiques par défaut en cas d'erreur"""
        return {
            "total_tickets": 0,
            "completed_tickets": 0,
            "waiting_tickets": 0,
            "serving_tickets": 0,
            "cancelled_tickets": 0,
            "no_show_tickets": 0,
            "average_wait_time": 0,
            "completion_rate": 0,
            "active_services": 0,
            "total_services": 0,
            "efficiency_rate": 0,
        }

    def _get_empty_dashboard_data(self):
        """Données vides en cas d'absence de services"""
        return {
            "services": [],
            "waiting_tickets": [],
            "serving_tickets": [],
            "stats": self._get_default_stats(),
            "last_update": fields.Datetime.now().strftime("%H:%M:%S"),
            "message": "Aucun service actif trouvé",
        }

    def _get_error_dashboard_data(self, error_message):
        """Données d'erreur pour le dashboard"""
        return {
            "services": [],
            "waiting_tickets": [],
            "serving_tickets": [],
            "stats": self._get_default_stats(),
            "last_update": fields.Datetime.now().strftime("%H:%M:%S"),
            "error": True,
            "error_message": error_message,
        }

    def _validate_dashboard_data(self, data):
        """Validation finale des données du dashboard"""
        required_keys = ["services", "waiting_tickets", "serving_tickets", "stats"]

        for key in required_keys:
            if key not in data:
                _logger.warning(f"Clé manquante dans dashboard_data: {key}")
                data[key] = [] if key != "stats" else self._get_default_stats()

        # Validation des services
        if not isinstance(data["services"], list):
            _logger.error("Format invalide pour 'services'")
            data["services"] = []

        # Validation des stats
        if not isinstance(data["stats"], dict):
            _logger.error("Format invalide pour 'stats'")
            data["stats"] = self._get_default_stats()

    def clear_stats_cache(self):
        """Vider le cache des statistiques - méthode robuste"""
        try:
            cache_keys = ["queue_dashboard_stats_data", "queue_dashboard_stats_time"]
            for key in cache_keys:
                self.env["ir.config_parameter"].sudo().set_param(key, "")
            _logger.debug("Cache des statistiques vidé avec succès")
        except Exception as e:
            _logger.warning(f"Erreur lors du vidage du cache: {e}")

    # Méthode alternative plus simple pour les cas critiques
    @api.model
    def get_dashboard_data_simple(self):
        """Version simplifiée et ultra-robuste pour les cas d'urgence"""
        try:
            services = self.search([("active", "=", True)])

            simple_data = {
                "services": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "is_open": s.is_open,
                        "waiting_count": len(s.waiting_ticket_ids),
                        "current_ticket": s.current_ticket_number,
                    }
                    for s in services
                ],
                "stats": {
                    "total_services": len(services),
                    "active_services": len(services.filtered("is_open")),
                },
                "last_update": fields.Datetime.now().strftime("%H:%M:%S"),
                "mode": "simple",
            }

            return simple_data

        except Exception as e:
            _logger.error(f"Erreur même dans la version simple: {e}")
            return {
                "services": [],
                "stats": {"error": True},
                "last_update": fields.Datetime.now().strftime("%H:%M:%S"),
                "error_message": str(e),
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

    @api.model
    def get_realtime_stats(self, use_cache=True):
        """Statistiques en temps réel avec système de cache"""

        cache_key = "queue_dashboard_stats"
        cache_duration = 30  # 30 secondes

        if use_cache:
            # Vérifier le cache
            cached_data = (
                self.env["ir.config_parameter"].sudo().get_param(f"{cache_key}_data")
            )
            cached_time = (
                self.env["ir.config_parameter"].sudo().get_param(f"{cache_key}_time")
            )

            if cached_data and cached_time:
                try:
                    cache_timestamp = datetime.fromisoformat(cached_time)
                    if (datetime.now() - cache_timestamp).seconds < cache_duration:
                        return json.loads(cached_data)
                except:
                    pass  # Cache invalide, continuer

        # Recalculer les données
        stats_data = self.get_dashboard_data()

        # Mettre en cache
        if use_cache:
            try:
                self.env["ir.config_parameter"].sudo().set_param(
                    f"{cache_key}_data", json.dumps(stats_data, default=str)
                )
                self.env["ir.config_parameter"].sudo().set_param(
                    f"{cache_key}_time", datetime.now().isoformat()
                )
            except:
                pass  # Erreur de cache non critique

        return stats_data

    def compute_service_efficiency(self):
        """Calculer l'efficacité d'un service"""
        self.ensure_one()

        today = fields.Date.today()
        today_tickets = self.ticket_ids.filtered(
            lambda t: t.created_time and t.created_time.date() == today
        )

        if not today_tickets:
            return {
                "efficiency_rate": 0,
                "throughput": 0,
                "avg_processing_time": 0,
                "utilization_rate": 0,
            }

        served_tickets = today_tickets.filtered(lambda t: t.state == "served")
        total_tickets = len(today_tickets)

        # Taux d'efficacité (tickets servis / tickets totaux)
        efficiency_rate = (
            (len(served_tickets) / total_tickets * 100) if total_tickets > 0 else 0
        )

        # Débit (tickets servis par heure)
        working_hours = self.working_hours_end - self.working_hours_start
        throughput = len(served_tickets) / working_hours if working_hours > 0 else 0

        # Temps de traitement moyen
        processing_times = [
            t.service_time for t in served_tickets if t.service_time > 0
        ]
        avg_processing_time = (
            sum(processing_times) / len(processing_times) if processing_times else 0
        )

        # Taux d'utilisation (temps effectif / temps disponible)
        total_service_time = sum(processing_times)
        available_minutes = working_hours * 60
        utilization_rate = (
            (total_service_time / available_minutes * 100)
            if available_minutes > 0
            else 0
        )

        return {
            "efficiency_rate": round(efficiency_rate, 2),
            "throughput": round(throughput, 2),
            "avg_processing_time": round(avg_processing_time, 2),
            "utilization_rate": round(min(utilization_rate, 100), 2),
            "total_served": len(served_tickets),
            "total_processing_time": round(total_service_time, 2),
        }

    @api.model
    def get_comparative_stats(self, days_back=7):
        """Obtenir des statistiques comparatives sur plusieurs jours"""
        end_date = fields.Date.today()
        start_date = end_date - timedelta(days=days_back)

        services = self.search([("active", "=", True)])
        daily_stats = {}

        # Calculer pour chaque jour
        current_date = start_date
        while current_date <= end_date:
            day_start = datetime.combine(current_date, datetime.min.time())
            day_end = datetime.combine(current_date, datetime.max.time())

            day_tickets = self.env["queue.ticket"].search(
                [
                    ("created_time", ">=", day_start),
                    ("created_time", "<=", day_end),
                    ("service_id", "in", services.ids),
                ]
            )

            daily_stats[current_date.isoformat()] = {
                "date": current_date.strftime("%Y-%m-%d"),
                "total_tickets": len(day_tickets),
                "served_tickets": len(
                    day_tickets.filtered(lambda t: t.state == "served")
                ),
                "cancelled_tickets": len(
                    day_tickets.filtered(lambda t: t.state == "cancelled")
                ),
                "avg_wait_time": self._calculate_avg_wait_time(day_tickets),
                "peak_hour": self._get_peak_hour(day_tickets),
            }

            current_date += timedelta(days=1)

        return daily_stats

    def _calculate_avg_wait_time(self, tickets):
        """Calculer le temps d'attente moyen pour un ensemble de tickets"""
        served_tickets = tickets.filtered(
            lambda t: t.state == "served" and t.waiting_time > 0
        )
        if served_tickets:
            return round(
                sum(t.waiting_time for t in served_tickets) / len(served_tickets), 2
            )
        return 0

    def _get_peak_hour(self, tickets):
        """Obtenir l'heure de pointe pour un ensemble de tickets"""
        if not tickets:
            return None

        hourly_count = {}
        for ticket in tickets:
            if ticket.created_time:
                hour = ticket.created_time.hour
                hourly_count[hour] = hourly_count.get(hour, 0) + 1

        if hourly_count:
            peak_hour = max(hourly_count, key=hourly_count.get)
            return f"{peak_hour:02d}:00"
        return None

    @api.model
    def get_dashboard_summary(self):
        """Résumé rapide pour les widgets ou notifications"""
        services = self.search([("active", "=", True)])

        total_waiting = sum(len(s.waiting_ticket_ids) for s in services)
        total_serving = len(
            self.env["queue.ticket"].search(
                [("state", "=", "serving"), ("service_id", "in", services.ids)]
            )
        )

        # Service le plus chargé
        busiest_service = max(
            services, key=lambda s: len(s.waiting_ticket_ids), default=None
        )

        # Alerte si file trop longue
        alerts = []
        for service in services:
            waiting_count = len(service.waiting_ticket_ids)
            if waiting_count > 10:  # Seuil configurable
                alerts.append(
                    {
                        "type": "warning",
                        "message": f"File d'attente longue pour {service.name}: {waiting_count} tickets",
                        "service_id": service.id,
                    }
                )

        return {
            "total_waiting": total_waiting,
            "total_serving": total_serving,
            "active_services": len(services.filtered("is_open")),
            "busiest_service": (
                {
                    "name": busiest_service.name,
                    "waiting_count": len(busiest_service.waiting_ticket_ids),
                }
                if busiest_service
                else None
            ),
            "alerts": alerts,
            "timestamp": fields.Datetime.now(),
        }

    # Ajout dans queue.service.py pour les rapports de performance

    @api.model
    def generate_performance_report(
        self, date_from=None, date_to=None, service_ids=None
    ):
        """Générer un rapport de performance détaillé"""

        if not date_from:
            date_from = fields.Date.today() - timedelta(days=7)
        if not date_to:
            date_to = fields.Date.today()

        # Domaine de recherche
        domain = [
            (
                "created_time",
                ">=",
                datetime.combine(date_from, datetime.min.time()),
            ),
            (
                "created_time",
                "<=",
                datetime.combine(date_to, datetime.max.time()),
            ),
        ]

        if service_ids:
            domain.append(("service_id", "in", service_ids))

        tickets = self.env["queue.ticket"].search(domain)
        services = (
            service_ids
            and self.browse(service_ids)
            or self.search([("active", "=", True)])
        )

        report_data = {
            "period": {
                "start": date_from.strftime("%d/%m/%Y"),
                "end": date_to.strftime("%d/%m/%Y"),
                "days": (date_to - date_from).days + 1,
            },
            "global_stats": self._calculate_global_performance(tickets),
            "services_performance": [],
            "daily_breakdown": self._get_daily_breakdown(tickets, date_from, date_to),
            "hourly_distribution": self._get_hourly_distribution(tickets),
            "satisfaction_analysis": self._get_satisfaction_analysis(tickets),
        }

        # Performance par service
        for service in services:
            service_tickets = tickets.filtered(lambda t: t.service_id.id == service.id)
            if service_tickets:
                performance = self._calculate_service_performance(
                    service, service_tickets
                )
                report_data["services_performance"].append(performance)

        return report_data

    def _calculate_global_performance(self, tickets):
        """Calculer les performances globales"""
        if not tickets:
            return {
                "total_tickets": 0,
                "completion_rate": 0,
                "avg_wait_time": 0,
                "avg_service_time": 0,
                "customer_satisfaction": 0,
            }

        served_tickets = tickets.filtered(lambda t: t.state == "served")

        return {
            "total_tickets": len(tickets),
            "served_tickets": len(served_tickets),
            "completion_rate": round((len(served_tickets) / len(tickets) * 100), 2),
            "cancelled_rate": round(
                (
                    len(tickets.filtered(lambda t: t.state == "cancelled"))
                    / len(tickets)
                    * 100
                ),
                2,
            ),
            "no_show_rate": round(
                (
                    len(tickets.filtered(lambda t: t.state == "no_show"))
                    / len(tickets)
                    * 100
                ),
                2,
            ),
            "avg_wait_time": (
                round(
                    sum(t.waiting_time for t in served_tickets if t.waiting_time > 0)
                    / len([t for t in served_tickets if t.waiting_time > 0]),
                    2,
                )
                if served_tickets
                else 0
            ),
            "avg_service_time": (
                round(
                    sum(t.service_time for t in served_tickets if t.service_time > 0)
                    / len([t for t in served_tickets if t.service_time > 0]),
                    2,
                )
                if served_tickets
                else 0
            ),
            "customer_satisfaction": self._calculate_satisfaction_rate(served_tickets),
        }

    def _calculate_service_performance(self, service, tickets):
        """Calculer les performances d'un service spécifique"""
        served_tickets = tickets.filtered(lambda t: t.state == "served")

        # Efficacité du service
        efficiency_data = service.compute_service_efficiency()

        return {
            "service_id": service.id,
            "service_name": service.name,
            "total_tickets": len(tickets),
            "served_tickets": len(served_tickets),
            "completion_rate": (
                round((len(served_tickets) / len(tickets) * 100), 2) if tickets else 0
            ),
            "avg_wait_time": (
                round(
                    sum(t.waiting_time for t in served_tickets if t.waiting_time > 0)
                    / len([t for t in served_tickets if t.waiting_time > 0]),
                    2,
                )
                if served_tickets
                else 0
            ),
            "avg_service_time": (
                round(
                    sum(t.service_time for t in served_tickets if t.service_time > 0)
                    / len([t for t in served_tickets if t.service_time > 0]),
                    2,
                )
                if served_tickets
                else 0
            ),
            "peak_load": (
                max(
                    [
                        len(tickets.filtered(lambda t: t.created_time.hour == h))
                        for h in range(24)
                    ]
                )
                if tickets
                else 0
            ),
            "efficiency_metrics": efficiency_data,
            "satisfaction_score": self._calculate_satisfaction_rate(served_tickets),
        }

    def _get_daily_breakdown(self, tickets, start_date, end_date):
        """Ventilation quotidienne des performances"""
        daily_data = []
        current_date = start_date

        while current_date <= end_date:
            day_tickets = tickets.filtered(
                lambda t: t.created_time.date() == current_date
            )

            daily_data.append(
                {
                    "date": current_date.strftime("%Y-%m-%d"),
                    "day_name": current_date.strftime("%A"),
                    "total_tickets": len(day_tickets),
                    "served_tickets": len(
                        day_tickets.filtered(lambda t: t.state == "served")
                    ),
                    "avg_wait_time": self._calculate_avg_wait_time(day_tickets),
                    "peak_hour": self._get_peak_hour(day_tickets),
                }
            )

            current_date += timedelta(days=1)

        return daily_data

    def _get_hourly_distribution(self, tickets):
        """Distribution horaire du trafic"""
        hourly_data = []

        for hour in range(24):
            hour_tickets = tickets.filtered(lambda t: t.created_time.hour == hour)
            hourly_data.append(
                {
                    "hour": f"{hour:02d}:00",
                    "ticket_count": len(hour_tickets),
                    "avg_wait_time": (
                        self._calculate_avg_wait_time(hour_tickets)
                        if hour_tickets
                        else 0
                    ),
                }
            )

        return hourly_data

    def _get_satisfaction_analysis(self, tickets):
        """Analyse de la satisfaction client"""
        rated_tickets = tickets.filtered("rating")

        if not rated_tickets:
            return {
                "total_responses": 0,
                "average_rating": 0,
                "rating_distribution": {},
                "response_rate": 0,
            }

        # Distribution des notes
        rating_distribution = {}
        for rating in ["1", "2", "3", "4", "5"]:
            count = len(rated_tickets.filtered(lambda t: t.rating == rating))
            rating_distribution[rating] = {
                "count": count,
                "percentage": (
                    round((count / len(rated_tickets) * 100), 1) if rated_tickets else 0
                ),
            }

        # Note moyenne
        total_rating = sum(int(t.rating) for t in rated_tickets)
        avg_rating = total_rating / len(rated_tickets) if rated_tickets else 0

        # Taux de réponse
        served_tickets = tickets.filtered(lambda t: t.state == "served")
        response_rate = (
            (len(rated_tickets) / len(served_tickets) * 100) if served_tickets else 0
        )

        return {
            "total_responses": len(rated_tickets),
            "average_rating": round(avg_rating, 2),
            "rating_distribution": rating_distribution,
            "response_rate": round(response_rate, 1),
            "satisfaction_percentage": round((avg_rating / 5 * 100), 1),
        }

    def _calculate_satisfaction_rate(self, tickets):
        """Calculer le taux de satisfaction"""
        rated_tickets = tickets.filtered("rating")
        if not rated_tickets:
            return 0

        total_rating = sum(int(t.rating) for t in rated_tickets)
        max_possible = len(rated_tickets) * 5

        return round((total_rating / max_possible * 100), 2)

    @api.model
    def get_alerts_and_recommendations(self):
        """Obtenir les alertes et recommandations pour le dashboard"""
        services = self.search([("active", "=", True)])
        alerts = []
        recommendations = []

        for service in services:
            waiting_count = len(service.waiting_ticket_ids)

            # Alerte file trop longue
            if waiting_count > 15:
                alerts.append(
                    {
                        "type": "danger",
                        "title": "File d'attente critique",
                        "message": f"{service.name}: {waiting_count} personnes en attente",
                        "action": "call_additional_staff",
                        "service_id": service.id,
                    }
                )
            elif waiting_count > 8:
                alerts.append(
                    {
                        "type": "warning",
                        "title": "File d'attente importante",
                        "message": f"{service.name}: {waiting_count} personnes en attente",
                        "action": "monitor_closely",
                        "service_id": service.id,
                    }
                )

            # Recommandation temps de service
            if service.avg_waiting_time > service.estimated_service_time * 2:
                recommendations.append(
                    {
                        "type": "optimization",
                        "title": "Optimisation du temps de service",
                        "message": f"{service.name}: Temps d'attente réel supérieur à l'estimation",
                        "suggested_action": "Réviser le temps de service estimé ou ajouter des ressources",
                    }
                )

            # Service fermé avec file d'attente
            if not service.is_open and waiting_count > 0:
                alerts.append(
                    {
                        "type": "info",
                        "title": "Service fermé avec file d'attente",
                        "message": f"{service.name}: {waiting_count} tickets en attente pour un service fermé",
                        "action": "consider_opening",
                        "service_id": service.id,
                    }
                )

        return {"alerts": alerts, "recommendations": recommendations}

    # Ajouter ces champs et méthodes dans la classe QueueService

    # Nouveaux champs pour une meilleure gestion des séquences
    sequence_padding = fields.Integer(
        "Longueur numéro séquence",
        default=4,
        help="Nombre de chiffres pour le numéro de ticket",
    )
    sequence_prefix = fields.Char(
        "Préfixe séquence", compute="_compute_sequence_prefix", store=True
    )
    last_ticket_number = fields.Integer("Dernier numéro attribué", readonly=True)

    # Remplacer la méthode existante _compute_next_ticket
    @api.depends("current_ticket_number", "last_ticket_number")
    def _compute_next_ticket(self):
        for service in self:
            # Le prochain numéro est soit current_ticket_number + 1, soit last_ticket_number + 1
            service.next_ticket_number = (
                max(service.current_ticket_number, service.last_ticket_number or 0) + 1
            )

    @api.depends("ticket_prefix")
    def _compute_sequence_prefix(self):
        for service in self:
            service.sequence_prefix = (service.ticket_prefix or "QUE").upper()

    # Nouvelle méthode pour générer le prochain numéro de séquence
    def _get_next_ticket_number(self):
        """Génère le prochain numéro de ticket de manière sécurisée"""
        self.ensure_one()

        # Utiliser une transaction pour éviter les conflits
        with self.env.cr.savepoint():
            # Verrouiller l'enregistrement du service pour éviter les doublons
            self.env.cr.execute(
                "SELECT next_ticket_number FROM queue_service WHERE id = %s FOR UPDATE",
                (self.id,),
            )

            # Récupérer la valeur actuelle
            result = self.env.cr.fetchone()
            current_next = result[0] if result else 1

            # Mettre à jour la valeur
            self.env.cr.execute(
                "UPDATE queue_service SET next_ticket_number = %s, last_ticket_number = %s WHERE id = %s",
                (current_next + 1, current_next, self.id),
            )

            return current_next

    # Remplacer la méthode generate_ticket
    def generate_ticket(self):
        """Générer un nouveau ticket avec gestion robuste des numéros"""
        self.ensure_one()

        if not self.is_open:
            raise UserError(_("Le service est actuellement fermé"))

        if self.total_tickets_today >= self.max_tickets_per_day:
            raise UserError(_("Nombre maximum de tickets atteint pour aujourd'hui"))

        try:
            # Obtenir le prochain numéro de manière sécurisée
            ticket_number = self._get_next_ticket_number()

            # Créer le ticket
            ticket = self.env["queue.ticket"].create(
                {
                    "service_id": self.id,
                    "ticket_number": ticket_number,
                    "customer_phone": self.env.context.get("customer_phone", ""),
                    "customer_email": self.env.context.get("customer_email", ""),
                }
            )

            # Mettre à jour le ticket actuel
            self.current_ticket_number = ticket_number

            return {
                "ticket_id": ticket.id,
                "ticket_number": ticket_number,
                "ticket_reference": ticket.ticket_reference,
                "short_reference": ticket.short_reference,
            }

        except Exception as e:
            _logger.error(f"Erreur génération ticket service {self.id}: {e}")
            raise UserError(_("Erreur lors de la génération du ticket: %s") % str(e))

    # Nouvelle méthode pour synchroniser les numéros
    def sync_ticket_numbers(self):
        """Synchroniser les numéros de tickets avec la base de données"""
        self.ensure_one()

        # Trouver le numéro maximum dans les tickets existants
        max_ticket = self.env["queue.ticket"].search(
            [("service_id", "=", self.id)], order="ticket_number desc", limit=1
        )

        if max_ticket:
            max_number = max_ticket.ticket_number
            # Mettre à jour les compteurs
            self.write(
                {
                    "current_ticket_number": max_number,
                    "last_ticket_number": max_number,
                    "next_ticket_number": max_number + 1,
                }
            )
            _logger.info(f"Synchronisé service {self.name}: numéro max = {max_number}")
            return max_number
        else:
            # Aucun ticket, réinitialiser
            self.write(
                {
                    "current_ticket_number": 0,
                    "last_ticket_number": 0,
                    "next_ticket_number": 1,
                }
            )
            _logger.info(
                f"Synchronisé service {self.name}: aucun ticket, réinitialisation"
            )
            return 0

    # Méthode pour réinitialiser la séquence
    def reset_sequence(self, start_number=1):
        """Réinitialiser la séquence de numérotation"""
        self.ensure_one()

        self.write(
            {
                "current_ticket_number": start_number - 1,
                "last_ticket_number": start_number - 1,
                "next_ticket_number": start_number,
            }
        )

        _logger.info(
            f"Séquence réinitialisée pour service {self.name} à {start_number}"
        )
        return True

    # Ajouter une contrainte pour éviter les numéros négatifs
    @api.constrains("current_ticket_number", "last_ticket_number", "next_ticket_number")
    def _check_ticket_numbers(self):
        for service in self:
            if service.current_ticket_number < 0:
                raise ValidationError(
                    _("Le numéro de ticket actuel ne peut pas être négatif")
                )
            if service.last_ticket_number < 0:
                raise ValidationError(
                    _("Le dernier numéro de ticket ne peut pas être négatif")
                )
            if service.next_ticket_number < 1:
                raise ValidationError(
                    _("Le prochain numéro de ticket doit être au moins 1")
                )

    # Dans queue_service.py
    def get_numbering_status(self):
        """Obtenir le statut de la numérotation"""
        self.ensure_one()

        tickets = self.env["queue.ticket"].search([("service_id", "=", self.id)])
        max_ticket = max(tickets.mapped("ticket_number")) if tickets else 0

        return {
            "service_name": self.name,
            "current_ticket_number": self.current_ticket_number,
            "last_ticket_number": self.last_ticket_number,
            "next_ticket_number": self.next_ticket_number,
            "max_ticket_in_db": max_ticket,
            "ticket_count": len(tickets),
            "is_synchronized": self.current_ticket_number == max_ticket,
            "last_sync": fields.Datetime.now(),
        }

    @api.model
    def get_dashboard_report_data(self):
        """
        Génère les données complètes pour les rapports du dashboard
        """
        try:
            # Récupérer les données de base du dashboard
            base_data = self.get_dashboard_data()

            # Ajouter les métriques d'efficacité
            efficiency_metrics = self._calculate_efficiency_metrics()

            # Analyser les tendances
            trend_analysis = self._analyze_trends()

            # Générer les recommandations
            recommendations = self._generate_recommendations(
                base_data, efficiency_metrics
            )

            return {
                **base_data,
                "efficiency_metrics": efficiency_metrics,
                "trend_analysis": trend_analysis,
                "recommendations": recommendations,
                "report_generated_at": fields.Datetime.now().isoformat(),
            }

        except Exception as e:
            _logger.error(f"Error generating report data: {str(e)}")
            raise UserError(f"Erreur lors de la génération du rapport: {str(e)}")

    def _calculate_efficiency_metrics(self):
        """
        Calcule les métriques d'efficacité
        """
        # Calculer le temps de service moyen
        serving_tickets = self.env["queue.ticket"].search(
            [("state", "=", "serving"), ("served_time", "!=", False)]
        )

        avg_service_time = 0
        if serving_tickets:
            total_duration = sum(
                ticket.service_duration or 0 for ticket in serving_tickets
            )
            avg_service_time = total_duration / len(serving_tickets)

        # Identifier les heures de pointe (simulation basée sur les données actuelles)
        peak_hours = self._identify_peak_hours()

        # Identifier les goulots d'étranglement
        bottleneck_services = self._identify_bottlenecks()

        # Calculer le score de satisfaction
        customer_satisfaction_score = self._calculate_satisfaction_score()

        return {
            "avg_service_time": avg_service_time,
            "peak_hours": peak_hours,
            "bottleneck_services": bottleneck_services,
            "customer_satisfaction_score": customer_satisfaction_score,
        }

    def _identify_peak_hours(self):
        """
        Identifie les heures de pointe basées sur l'historique des tickets
        """
        # Analyser les tickets d'aujourd'hui
        today = fields.Date.today()
        tickets_today = self.env["queue.ticket"].search(
            [
                ("create_date", ">=", today),
                ("create_date", "<", today + timedelta(days=1)),
            ]
        )

        # Grouper par heure
        hourly_counts = {}
        for ticket in tickets_today:
            hour = ticket.create_date.hour
            hourly_counts[hour] = hourly_counts.get(hour, 0) + 1

        # Trouver les pics
        if hourly_counts:
            max_hour = max(hourly_counts, key=hourly_counts.get)
            highest_load_hour = f"{max_hour:02d}:00"
        else:
            highest_load_hour = "10:00"

        return {
            "morning_peak": "09:00-11:00",
            "afternoon_peak": "14:00-16:00",
            "highest_load_hour": highest_load_hour,
        }

    def _identify_bottlenecks(self):
        """
        Identifie les services en goulot d'étranglement
        """
        services = self.search([("is_active", "=", True)])
        bottlenecks = []

        for service in services:
            capacity_percentage = service._calculate_capacity_percentage()
            if capacity_percentage > 80:
                waiting_count = len(service.waiting_ticket_ids)
                severity = "critical" if capacity_percentage > 95 else "high"

                bottlenecks.append(
                    {
                        "name": service.name,
                        "capacity_percentage": capacity_percentage,
                        "waiting_count": waiting_count,
                        "severity": severity,
                    }
                )

        return bottlenecks

    def _calculate_satisfaction_score(self):
        """
        Calcule un score de satisfaction approximatif
        """
        # Récupérer les statistiques globales
        stats = self._get_global_stats()

        avg_wait_time = stats.get("average_wait_time", 0)
        completion_rate = stats.get("completion_rate", 0)

        # Score basé sur le temps d'attente et le taux de completion
        score = 100
        score -= min(avg_wait_time * 2, 40)  # Pénalité pour temps d'attente élevé
        score = score * completion_rate / 100  # Ajusté par le taux de completion

        return max(0, min(100, score))

    def _analyze_trends(self):
        """
        Analyse les tendances des données
        """
        # Analyser la tendance quotidienne
        daily_trend = self._analyze_daily_trend()

        # Analyser les patterns d'usage des services
        service_usage_patterns = self._analyze_service_usage_patterns()

        # Analyser les tendances des temps d'attente
        waiting_time_trends = self._analyze_waiting_time_trends()

        return {
            "daily_trend": daily_trend,
            "service_usage_patterns": service_usage_patterns,
            "waiting_time_trends": waiting_time_trends,
        }

    def _analyze_daily_trend(self):
        """
        Analyse la tendance quotidienne des tickets
        """
        # Comparer avec les 7 derniers jours
        today = fields.Date.today()
        week_ago = today - timedelta(days=7)

        tickets_today = self.env["queue.ticket"].search_count(
            [
                ("create_date", ">=", today),
                ("create_date", "<", today + timedelta(days=1)),
            ]
        )

        tickets_week_avg = (
            self.env["queue.ticket"].search_count(
                [("create_date", ">=", week_ago), ("create_date", "<", today)]
            )
            / 7
        )

        if tickets_week_avg > 0:
            change_percentage = (
                (tickets_today - tickets_week_avg) / tickets_week_avg
            ) * 100
        else:
            change_percentage = 0

        if change_percentage > 5:
            trend = "increasing"
        elif change_percentage < -5:
            trend = "decreasing"
        else:
            trend = "stable"

        return {"trend": trend, "change_percentage": round(change_percentage, 2)}

    def _analyze_service_usage_patterns(self):
        """
        Analyse les patterns d'usage des services
        """
        services = self.search([("is_active", "=", True)])
        patterns = []

        for service in services:
            total_tickets_today = len(
                service.ticket_ids.filtered(
                    lambda t: t.create_date.date() == fields.Date.today()
                )
            )

            usage_level = (
                "high"
                if total_tickets_today > 50
                else "medium" if total_tickets_today > 20 else "low"
            )
            efficiency = self._calculate_service_efficiency(service)

            patterns.append(
                {
                    "name": service.name,
                    "usage_level": usage_level,
                    "efficiency": efficiency,
                }
            )

        return patterns

    def _calculate_service_efficiency(self, service):
        """
        Calcule l'efficacité d'un service
        """
        today = fields.Date.today()
        tickets_today = service.ticket_ids.filtered(
            lambda t: t.create_date.date() == today
        )

        if not tickets_today:
            return 0

        completed = len(tickets_today.filtered(lambda t: t.state == "served"))
        total = len(tickets_today)

        return round((completed / total) * 100) if total > 0 else 0

    def _analyze_waiting_time_trends(self):
        """
        Analyse les tendances des temps d'attente
        """
        stats = self._get_global_stats()
        avg_wait_time = stats.get("average_wait_time", 0)

        status = (
            "excellent"
            if avg_wait_time < 5
            else "good" if avg_wait_time < 10 else "needs_improvement"
        )
        target_improvement = max(0, avg_wait_time - 5)

        return {
            "current_avg": avg_wait_time,
            "status": status,
            "target_improvement": target_improvement,
        }

    def _generate_recommendations(self, dashboard_data, efficiency_metrics):
        """
        Génère des recommandations basées sur l'analyse des données
        """
        recommendations = []

        # Recommandations basées sur les goulots d'étranglement
        bottlenecks = efficiency_metrics.get("bottleneck_services", [])
        if bottlenecks:
            affected_services = [b["name"] for b in bottlenecks]
            recommendations.append(
                {
                    "type": "capacity",
                    "priority": "high",
                    "message": f"{len(bottlenecks)} service(s) en surcharge détecté(s). Considérez augmenter la capacité.",
                    "affected_services": affected_services,
                }
            )

        # Recommandations basées sur le temps d'attente
        avg_wait_time = dashboard_data.get("stats", {}).get("average_wait_time", 0)
        if avg_wait_time > 10:
            recommendations.append(
                {
                    "type": "efficiency",
                    "priority": "medium",
                    "message": "Le temps d'attente moyen est élevé. Optimisez les processus de service.",
                    "current_avg": avg_wait_time,
                    "target_avg": 5,
                }
            )

        # Recommandations basées sur les tickets annulés
        stats = dashboard_data.get("stats", {})
        total_tickets = stats.get("total_tickets", 1)
        cancelled_tickets = stats.get("cancelled_tickets", 0) + stats.get(
            "no_show_tickets", 0
        )
        cancelled_rate = (cancelled_tickets / max(total_tickets, 1)) * 100

        if cancelled_rate > 10:
            recommendations.append(
                {
                    "type": "retention",
                    "priority": "medium",
                    "message": "Taux d'abandon élevé. Améliorez la communication et réduisez les temps d'attente.",
                    "cancelled_rate": round(cancelled_rate, 2),
                }
            )

        return recommendations

    @api.model
    def generate_excel_export(self, data):
        """
        Génère un export Excel des données du dashboard
        """
        try:
            # Importer xlsxwriter si disponible, sinon utiliser une alternative
            try:
                import xlsxwriter
            except ImportError:
                raise UserError("Module xlsxwriter requis pour l'export Excel")

            # Créer un buffer en mémoire
            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output)

            # Formats
            header_format = workbook.add_format(
                {
                    "bold": True,
                    "bg_color": "#366092",
                    "font_color": "white",
                    "border": 1,
                }
            )

            cell_format = workbook.add_format({"border": 1})
            number_format = workbook.add_format({"border": 1, "num_format": "0.00"})

            # Feuille Résumé
            summary_sheet = workbook.add_worksheet("Résumé")
            self._write_summary_sheet(summary_sheet, data, header_format, cell_format)

            # Feuille Services
            services_sheet = workbook.add_worksheet("Services")
            self._write_services_sheet(
                services_sheet, data, header_format, cell_format, number_format
            )

            # Feuille Tickets en Attente
            waiting_sheet = workbook.add_worksheet("Tickets en Attente")
            self._write_waiting_tickets_sheet(
                waiting_sheet, data, header_format, cell_format
            )

            # Feuille Tickets en Service
            serving_sheet = workbook.add_worksheet("Tickets en Service")
            self._write_serving_tickets_sheet(
                serving_sheet, data, header_format, cell_format
            )

            workbook.close()
            output.seek(0)

            # Encoder en base64
            file_content = base64.b64encode(output.read()).decode()
            output.close()

            return {
                "file_content": file_content,
                "filename": f'dashboard_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx',
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }

        except Exception as e:
            _logger.error(f"Excel export error: {str(e)}")
            raise UserError(f"Erreur lors de l'export Excel: {str(e)}")

    def _write_summary_sheet(self, sheet, data, header_format, cell_format):
        """
        Écrit la feuille de résumé
        """
        sheet.write(0, 0, "Métrique", header_format)
        sheet.write(0, 1, "Valeur", header_format)

        summary_data = [
            ("Total Tickets", data["summary"]["total_tickets"]),
            ("Tickets Terminés", data["summary"]["completed_tickets"]),
            ("Tickets en Attente", data["summary"]["waiting_tickets"]),
            ("Tickets en Service", data["summary"]["serving_tickets"]),
            ("Tickets Annulés", data["summary"]["cancelled_tickets"]),
            ("Tickets Non-Présentés", data["summary"]["no_show_tickets"]),
            ("Temps d'Attente Moyen (min)", data["summary"]["average_wait_time"]),
            ("Taux de Completion (%)", data["summary"]["completion_rate"]),
            ("Services Actifs", data["summary"]["active_services"]),
            ("Total Services", data["summary"]["total_services"]),
        ]

        for row, (metric, value) in enumerate(summary_data, 1):
            sheet.write(row, 0, metric, cell_format)
            sheet.write(row, 1, value, cell_format)

        # Ajuster la largeur des colonnes
        sheet.set_column(0, 0, 25)
        sheet.set_column(1, 1, 15)

    def _write_services_sheet(
        self, sheet, data, header_format, cell_format, number_format
    ):
        """
        Écrit la feuille des services
        """
        headers = [
            "ID",
            "Nom du Service",
            "Ouvert",
            "En Attente",
            "En Service",
            "Terminés",
            "Total Aujourd'hui",
            "Temps Attente Moyen",
            "Capacité %",
        ]

        for col, header in enumerate(headers):
            sheet.write(0, col, header, header_format)

        for row, service in enumerate(data["services"], 1):
            sheet.write(row, 0, service["id"], cell_format)
            sheet.write(row, 1, service["name"], cell_format)
            sheet.write(row, 2, "Oui" if service["is_open"] else "Non", cell_format)
            sheet.write(row, 3, service["waiting_count"], cell_format)
            sheet.write(row, 4, service["serving_count"], cell_format)
            sheet.write(row, 5, service["served_count"], cell_format)
            sheet.write(row, 6, service["total_tickets_today"], cell_format)
            sheet.write(row, 7, service["avg_waiting_time"], number_format)
            sheet.write(row, 8, service["capacity_percentage"], number_format)

        # Ajuster la largeur des colonnes
        sheet.set_column(0, 0, 8)
        sheet.set_column(1, 1, 20)
        sheet.set_column(2, 8, 12)

    def _write_waiting_tickets_sheet(self, sheet, data, header_format, cell_format):
        """
        Écrit la feuille des tickets en attente
        """
        headers = [
            "ID",
            "Numéro",
            "Service",
            "Client",
            "Créé le",
            "Priorité",
            "Position",
            "Attente Estimée (min)",
        ]

        for col, header in enumerate(headers):
            sheet.write(0, col, header, header_format)

        for row, ticket in enumerate(data["waiting_tickets"], 1):
            sheet.write(row, 0, ticket["id"], cell_format)
            sheet.write(row, 1, ticket["number"], cell_format)
            sheet.write(row, 2, ticket["service_name"], cell_format)
            sheet.write(row, 3, ticket["customer_name"], cell_format)
            sheet.write(row, 4, ticket["created_time"], cell_format)
            sheet.write(row, 5, ticket["priority"], cell_format)
            sheet.write(row, 6, ticket["position_in_queue"], cell_format)
            sheet.write(row, 7, ticket["estimated_wait"], cell_format)

        # Ajuster la largeur des colonnes
        sheet.set_column(0, 1, 10)
        sheet.set_column(2, 4, 15)
        sheet.set_column(5, 7, 12)

    def _write_serving_tickets_sheet(self, sheet, data, header_format, cell_format):
        """
        Écrit la feuille des tickets en service
        """
        headers = [
            "ID",
            "Numéro",
            "Service",
            "Client",
            "Créé le",
            "Appelé le",
            "Agent",
            "Durée Service (min)",
        ]

        for col, header in enumerate(headers):
            sheet.write(0, col, header, header_format)

        for row, ticket in enumerate(data["serving_tickets"], 1):
            sheet.write(row, 0, ticket["id"], cell_format)
            sheet.write(row, 1, ticket["number"], cell_format)
            sheet.write(row, 2, ticket["service_name"], cell_format)
            sheet.write(row, 3, ticket["customer_name"], cell_format)
            sheet.write(row, 4, ticket["created_time"], cell_format)
            sheet.write(row, 5, ticket["served_time"], cell_format)
            sheet.write(row, 6, ticket["agent_name"], cell_format)
            sheet.write(row, 7, ticket["service_duration"], cell_format)

        # Ajuster la largeur des colonnes
        sheet.set_column(0, 1, 10)
        sheet.set_column(2, 6, 15)
        sheet.set_column(7, 7, 12)

    # @api.model
    # def generate_pdf_report(self, data):
    #     """
    #     Génère un rapport PDF des données du dashboard
    #     """
    #     try:
    #         # Utiliser le système de rapports d'Odoo
    #         report_name = "queue_management.dashboard_report_template"

    #         # Créer un contexte avec les données
    #         context = {
    #             "report_data": data,
    #             "generated_at": datetime.now(),
    #             "company": self.env.company,
    #         }

    #         # Générer le PDF via le moteur de rapports d'Odoo
    #         pdf_content, _ = self.env["ir.actions.report"]._render_qweb_pdf(
    #             report_name, res_ids=[], data={"context": context}
    #         )

    #         return {
    #             "file_content": base64.b64encode(pdf_content).decode(),
    #             "filename": f'dashboard_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf',
    #             "mime_type": "application/pdf",
    #         }

    #     except Exception as e:
    #         _logger.error(f"PDF export error: {str(e)}")
    #         # Fallback: générer un PDF simple avec reportlab si disponible
    #         return self._generate_simple_pdf_report(data)

    def _generate_simple_pdf_report(self, data):
        """
        Génère un PDF simple avec reportlab
        """
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter, A4
            from reportlab.lib import colors
            from reportlab.platypus import (
                SimpleDocTemplate,
                Table,
                TableStyle,
                Paragraph,
                Spacer,
            )
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            styles = getSampleStyleSheet()
            story = []

            # Titre
            title_style = ParagraphStyle(
                "CustomTitle",
                parent=styles["Heading1"],
                fontSize=24,
                spaceAfter=30,
                alignment=1,  # Centré
            )
            story.append(Paragraph("Rapport Queue Management", title_style))
            story.append(
                Paragraph(
                    f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
                    styles["Normal"],
                )
            )
            story.append(Spacer(1, 20))

            # Résumé des statistiques
            story.append(Paragraph("Résumé Exécutif", styles["Heading2"]))

            summary_data = [
                ["Métrique", "Valeur"],
                ["Total Tickets", str(data["summary"]["total_tickets"])],
                ["Tickets Terminés", str(data["summary"]["completed_tickets"])],
                ["Tickets en Attente", str(data["summary"]["waiting_tickets"])],
                ["Tickets en Service", str(data["summary"]["serving_tickets"])],
                [
                    "Temps d'Attente Moyen",
                    f"{data['summary']['average_wait_time']:.1f} min",
                ],
                ["Taux de Completion", f"{data['summary']['completion_rate']:.1f}%"],
            ]

            summary_table = Table(summary_data)
            summary_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 14),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                        ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                        ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ]
                )
            )

            story.append(summary_table)
            story.append(Spacer(1, 20))

            # Services
            if data["services"]:
                story.append(Paragraph("Détail des Services", styles["Heading2"]))

                services_data = [
                    ["Service", "En Attente", "En Service", "Terminés", "Temps Moyen"]
                ]
                for service in data["services"]:
                    services_data.append(
                        [
                            service["name"],
                            str(service["waiting_count"]),
                            str(service["serving_count"]),
                            str(service["served_count"]),
                            f"{service['avg_waiting_time']:.1f} min",
                        ]
                    )

                services_table = Table(services_data)
                services_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, 0), 12),
                            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                            ("GRID", (0, 0), (-1, -1), 1, colors.black),
                        ]
                    )
                )

                story.append(services_table)
                story.append(Spacer(1, 20))

            # Recommandations
            if data.get("recommendations"):
                story.append(Paragraph("Recommandations", styles["Heading2"]))
                for rec in data["recommendations"]:
                    priority_text = f"[{rec['priority'].upper()}]"
                    story.append(
                        Paragraph(f"{priority_text} {rec['message']}", styles["Normal"])
                    )
                    story.append(Spacer(1, 6))

            # Construire le PDF
            doc.build(story)
            buffer.seek(0)

            pdf_content = buffer.read()
            buffer.close()

            return {
                "file_content": base64.b64encode(pdf_content).decode(),
                "filename": f'dashboard_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf',
                "mime_type": "application/pdf",
            }

        except ImportError:
            raise UserError("Modules reportlab requis pour la génération de PDF")
        except Exception as e:
            _logger.error(f"PDF generation error: {str(e)}")
            raise UserError(f"Erreur lors de la génération du PDF: {str(e)}")

    @api.model
    def export_report(self, report_data, format_type):
        """
        Exporte un rapport dans le format spécifié
        """
        try:
            if format_type == "excel":
                return self.generate_excel_export(report_data)
            elif format_type == "pdf":
                return self.generate_pdf_report(report_data)
            elif format_type == "json":
                json_content = json.dumps(report_data, indent=2, ensure_ascii=False)
                return {
                    "file_content": base64.b64encode(
                        json_content.encode("utf-8")
                    ).decode(),
                    "filename": f'dashboard_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json',
                    "mime_type": "application/json",
                }
            elif format_type == "csv":
                csv_content = self._generate_csv_content(report_data)
                return {
                    "file_content": base64.b64encode(
                        csv_content.encode("utf-8")
                    ).decode(),
                    "filename": f'dashboard_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv',
                    "mime_type": "text/csv",
                }
            else:
                raise UserError(f"Format d'export non supporté: {format_type}")

        except Exception as e:
            _logger.error(f"Export error: {str(e)}")
            raise UserError(f"Erreur lors de l'export: {str(e)}")

    def _generate_csv_content(self, data):
        """
        Génère le contenu CSV
        """
        import csv
        from io import StringIO

        output = StringIO()

        # Section Statistiques
        output.write("STATISTIQUES GENERALES\n")
        output.write("Métrique,Valeur\n")
        for key, value in data["summary"].items():
            formatted_key = key.replace("_", " ").title()
            output.write(f"{formatted_key},{value}\n")
        output.write("\n")

        # Section Services
        output.write("SERVICES\n")
        if data["services"]:
            writer = csv.DictWriter(output, fieldnames=data["services"][0].keys())
            writer.writeheader()
            writer.writerows(data["services"])
        output.write("\n")

        # Section Tickets en Attente
        output.write("TICKETS EN ATTENTE\n")
        if data["waiting_tickets"]:
            writer = csv.DictWriter(
                output, fieldnames=data["waiting_tickets"][0].keys()
            )
            writer.writeheader()
            writer.writerows(data["waiting_tickets"])
        output.write("\n")

        # Section Tickets en Service
        output.write("TICKETS EN SERVICE\n")
        if data["serving_tickets"]:
            writer = csv.DictWriter(
                output, fieldnames=data["serving_tickets"][0].keys()
            )
            writer.writeheader()
            writer.writerows(data["serving_tickets"])

        content = output.getvalue()
        output.close()
        return content

    def _calculate_capacity_percentage(self):
        """
        Calcule le pourcentage de capacité d'un service
        """
        if not self.max_capacity:
            return 0

        current_load = len(self.waiting_ticket_ids) + len(self.serving_ticket_ids)
        return min(100, (current_load / self.max_capacity) * 100)

    def _get_global_stats(self):
        """
        Récupère les statistiques globales pour tous les services
        """
        # Cette méthode devrait être cohérente avec get_dashboard_data
        all_tickets = self.env["queue.ticket"].search([])
        today_tickets = all_tickets.filtered(
            lambda t: t.create_date.date() == fields.Date.today()
        )

        waiting_tickets = today_tickets.filtered(lambda t: t.state == "waiting")
        serving_tickets = today_tickets.filtered(lambda t: t.state == "serving")
        completed_tickets = today_tickets.filtered(lambda t: t.state == "served")
        cancelled_tickets = today_tickets.filtered(
            lambda t: t.state in ["cancelled", "no_show"]
        )

        # Calculer le temps d'attente moyen
        avg_wait_time = 0
        if completed_tickets:
            total_wait = sum(
                ticket.waiting_duration or 0 for ticket in completed_tickets
            )
            avg_wait_time = total_wait / len(completed_tickets)

        # Calculer le taux de completion
        completion_rate = 0
        if today_tickets:
            completion_rate = (len(completed_tickets) / len(today_tickets)) * 100

        return {
            "waiting_tickets": len(waiting_tickets),
            "serving_tickets": len(serving_tickets),
            "completed_tickets": len(completed_tickets),
            "cancelled_tickets": len(cancelled_tickets),
            "average_wait_time": avg_wait_time,
            "completion_rate": completion_rate,
        }

    # Dans queue_service.py - Ajouter cette méthode
    @api.model
    def scheduled_ticket_number_maintenance(self):
        """Maintenance programmée de la numérotation des tickets"""
        try:
            # 1. Synchroniser tous les services
            services = self.search([("active", "=", True)])
            sync_count = 0

            for service in services:
                try:
                    service.sync_ticket_numbers()
                    sync_count += 1
                except Exception as e:
                    _logger.error(f"Erreur synchronisation service {service.id}: {e}")

            # 2. Vérifier les doublons
            duplicate_check = self.env["queue.ticket"].check_duplicate_ticket_numbers()

            # 3. Log des résultats
            _logger.info(
                f"Maintenance numérotation: {sync_count} services synchronisés, "
                f"{duplicate_check.get('duplicates', 0)} doublons détectés"
            )

            return {
                "synchronized_services": sync_count,
                "duplicates_found": duplicate_check.get("duplicates", 0),
                "timestamp": fields.Datetime.now(),
            }

        except Exception as e:
            _logger.error(f"Erreur maintenance numérotation: {e}")
            return {"error": str(e)}

    # Dans queue_ticket.py - Ajouter cette méthode
    @api.model
    def check_duplicate_ticket_numbers(self):
        """Vérifier les numéros de ticket en double"""
        try:
            # Rechercher les doublons par service
            duplicates = self.env.cr.execute(
                """
                SELECT service_id, ticket_number, COUNT(*)
                FROM queue_ticket
                WHERE ticket_number IS NOT NULL
                GROUP BY service_id, ticket_number
                HAVING COUNT(*) > 1
            """
            )

            results = self.env.cr.fetchall()

            if results:
                _logger.warning(
                    f"Doublons détectés: {len(results)} paires service/numéro"
                )
                # Log détaillé
                for service_id, ticket_number, count in results:
                    service = self.env["queue.service"].browse(service_id)
                    _logger.warning(
                        f"Service {service.name}: numéro {ticket_number} apparait {count} fois"
                    )

            return {"duplicates": len(results), "details": results}

        except Exception as e:
            _logger.error(f"Erreur vérification doublons: {e}")
            return {"duplicates": 0, "error": str(e)}

    def generate_pdf_report(self, dashboard_data):
        """
        Méthode serveur pour générer un PDF (fallback)
        """
        try:
            # Convertir les données en JSON string
            data_str = json.dumps(dashboard_data, ensure_ascii=False, indent=2)
            
            # Créer un PDF simple avec reportlab (si installé)
            try:
                from reportlab.pdfgen import canvas
                from reportlab.lib.pagesizes import letter
                
                buffer = BytesIO()
                p = canvas.Canvas(buffer, pagesize=letter)
                p.setFont("Helvetica", 10)
                
                # Titre
                p.drawString(100, 750, "Rapport Dashboard Queue Management")
                p.drawString(100, 735, f"Généré le: {fields.Datetime.now()}")
                
                # Données brutes (simplifiées)
                y = 700
                p.drawString(100, y, "Données du dashboard (format JSON):")
                y -= 20
                
                # Ajouter les données JSON
                lines = data_str.split('\n')
                for line in lines[:30]:  # Limiter pour éviter les PDF trop longs
                    if y < 50:
                        p.showPage()
                        y = 750
                    p.drawString(110, y, line)
                    y -= 15
                
                p.save()
                pdf_content = buffer.getvalue()
                buffer.close()
                
                return {
                    'file_content': base64.b64encode(pdf_content).decode('utf-8'),
                    'file_type': 'application/pdf'
                }
                
            except ImportError:
                # Fallback: retourner les données JSON si reportlab n'est pas installé
                return {
                    'file_content': base64.b64encode(data_str.encode('utf-8')).decode('utf-8'),
                    'file_type': 'application/json',
                    'warning': 'ReportLab non installé, données JSON fournies'
                }
                
        except Exception as e:
            return {
                'error': f'Erreur lors de la génération du PDF: {str(e)}'
            }