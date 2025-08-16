# models/queue_config.py
# Configuration et optimisations pour les performances

from odoo import models, fields, api, tools
import logging

_logger = logging.getLogger(__name__)


class QueueConfiguration(models.Model):
    _name = "queue.config"
    _description = "Configuration du Système de File d'Attente"
    _rec_name = "name"

    name = fields.Char(
        "Nom de Configuration", required=True, default="Configuration Principale"
    )

    # Paramètres de performance
    dashboard_refresh_interval = fields.Integer(
        "Intervalle Actualisation Dashboard (sec)", default=15
    )
    cache_duration = fields.Integer("Durée Cache (sec)", default=30)
    auto_cleanup_enabled = fields.Boolean("Nettoyage Automatique", default=True)
    cleanup_days_to_keep = fields.Integer("Jours à Conserver", default=30)

    # Paramètres d'alertes
    max_waiting_alert = fields.Integer("Seuil Alerte File d'Attente", default=15)
    long_service_alert = fields.Integer("Seuil Service Long (min)", default=30)
    enable_email_notifications = fields.Boolean("Notifications Email", default=True)
    enable_sms_notifications = fields.Boolean("Notifications SMS", default=False)

    # Paramètres d'affichage
    show_customer_names = fields.Boolean("Afficher Noms Clients", default=True)
    show_estimated_times = fields.Boolean("Afficher Temps Estimés", default=True)
    show_statistics = fields.Boolean("Afficher Statistiques", default=True)

    # Paramètres de sécurité
    allow_ticket_cancellation = fields.Boolean(
        "Permettre Annulation Tickets", default=True
    )
    require_customer_info = fields.Boolean("Exiger Infos Client", default=False)
    enable_feedback = fields.Boolean("Activer Feedback", default=True)

    # Paramètres d'annulation
    max_cancellation_delay_minutes = fields.Integer(
        "Délai max annulation (min)", default=30
    )
    require_cancellation_reason = fields.Boolean("Raison obligatoire", default=False)
    max_cancellations_per_ip = fields.Integer("Max annulations par IP/10min", default=5)

    # Notifications
    notify_cancellation_email = fields.Boolean("Email annulation", default=True)
    cancellation_alert_threshold = fields.Float("Seuil alerte taux (%)", default=30.0)

    # Nettoyage automatique
    auto_cleanup_cancelled_tickets = fields.Boolean(
        "Nettoyage auto tickets annulés", default=True
    )
    cleanup_delay_days = fields.Integer("Délai nettoyage (jours)", default=30)

    @api.model
    def get_config(self):
        """Obtenir la configuration active"""
        config = self.search([], limit=1)
        if not config:
            config = self.create({})
        return config

    @api.model
    def get_current_config(self):
        """Obtenir la configuration actuelle"""
        config = self.search([("name", "=", "Configuration Principale")], limit=1)

        if not config:
            # Créer une configuration par défaut
            config = self.create({"name": "Configuration Principale"})

        return config

    def apply_configuration(self):
        """Appliquer cette configuration au système"""
        self.ensure_one()

        config_param_model = self.env["ir.config_parameter"].sudo()

        # Mettre à jour les paramètres système
        params_mapping = {
            "queue_management.default_refresh_interval": str(
                self.dashboard_refresh_interval
            ),
            "queue_management.cache_duration_seconds": str(self.cache_duration),
            "queue_management.max_waiting_alert_threshold": str(self.max_waiting_alert),
            "queue_management.auto_cleanup_enabled": str(self.auto_cleanup_enabled),
            "queue_management.cleanup_days_to_keep": str(self.cleanup_days_to_keep),
            "queue_management.enable_notifications": str(
                self.enable_email_notifications
            ),
            "queue_management.enable_sms": str(self.enable_sms_notifications),
            "queue_management.show_customer_names": str(self.show_customer_names),
            "queue_management.require_customer_info": str(self.require_customer_info),
        }

        for key, value in params_mapping.items():
            config_param_model.set_param(key, value)

        # Vider le cache pour appliquer les nouveaux paramètres
        self.env["queue.service"].clear_stats_cache()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Configuration Appliquée",
                "message": "Les paramètres ont été mis à jour avec succès",
                "type": "success",
            },
        }


# Modèle pour les métriques de performance
class QueuePerformanceMetrics(models.Model):
    _name = "queue.performance.metrics"
    _description = "Métriques de Performance"
    _order = "date desc"

    date = fields.Date("Date", required=True, index=True)
    service_id = fields.Many2one("queue.service", "Service", index=True)

    # Métriques quotidiennes
    total_tickets = fields.Integer("Total Tickets")
    served_tickets = fields.Integer("Tickets Servis")
    cancelled_tickets = fields.Integer("Tickets Annulés")
    no_show_tickets = fields.Integer("Tickets Absents")

    # Temps moyens
    avg_waiting_time = fields.Float("Temps Attente Moyen (min)")
    avg_service_time = fields.Float("Temps Service Moyen (min)")

    # Efficacité
    completion_rate = fields.Float("Taux de Completion (%)")
    satisfaction_rate = fields.Float("Taux de Satisfaction (%)")

    # Capacité
    capacity_utilization = fields.Float("Utilisation Capacité (%)")
    peak_hour = fields.Char("Heure de Pointe")
    peak_load = fields.Integer("Charge Maximale")

    @api.model
    def collect_daily_metrics(self, target_date=None):
        """Collecter les métriques quotidiennes"""
        if not target_date:
            target_date = fields.Date.today() - timedelta(days=1)  # Hier

        services = self.env["queue.service"].search([("active", "=", True)])

        for service in services:
            # Vérifier si les métriques existent déjà
            existing = self.search(
                [("date", "=", target_date), ("service_id", "=", service.id)]
            )

            if existing:
                continue  # Déjà collecté

            # Calculer les métriques
            stats = service.get_detailed_stats(target_date, target_date)

            # Créer l'enregistrement
            self.create(
                {
                    "date": target_date,
                    "service_id": service.id,
                    "total_tickets": stats["total_tickets"],
                    "served_tickets": stats["served_tickets"],
                    "cancelled_tickets": stats["cancelled_tickets"],
                    "no_show_tickets": stats["no_show_tickets"],
                    "avg_waiting_time": stats["avg_waiting_time"],
                    "avg_service_time": stats["avg_service_time"],
                    "completion_rate": stats["efficiency_rate"],
                    "satisfaction_rate": stats["satisfaction_rate"],
                    "capacity_utilization": self._calculate_capacity_utilization(
                        service, stats
                    ),
                    "peak_hour": self._get_peak_hour_from_stats(stats),
                    "peak_load": (
                        max(stats.get("hourly_distribution", {}).values())
                        if stats.get("hourly_distribution")
                        else 0
                    ),
                }
            )

        _logger.info(
            f"Métriques collectées pour {len(services)} services le {target_date}"
        )

    def _calculate_capacity_utilization(self, service, stats):
        """Calculer l'utilisation de la capacité"""
        if service.max_tickets_per_day > 0:
            return (stats["total_tickets"] / service.max_tickets_per_day) * 100
        return 0

    def _get_peak_hour_from_stats(self, stats):
        """Extraire l'heure de pointe des statistiques"""
        hourly_dist = stats.get("hourly_distribution", {})
        if hourly_dist:
            peak_hour = max(hourly_dist, key=hourly_dist.get)
            return f"{peak_hour:02d}:00"
        return None

    @api.model
    def get_trends_analysis(self, days_back=30):
        """Analyser les tendances sur une période"""
        end_date = fields.Date.today()
        start_date = end_date - timedelta(days=days_back)

        metrics = self.search(
            [("date", ">=", start_date), ("date", "<=", end_date)], order="date"
        )

        if not metrics:
            return {"error": "Pas de données pour cette période"}

        # Analyse des tendances
        trends = {}
        services = metrics.mapped("service_id")

        for service in services:
            service_metrics = metrics.filtered(lambda m: m.service_id.id == service.id)

            if len(service_metrics) < 2:
                continue

            # Calculer les tendances
            first_week = (
                service_metrics[:7] if len(service_metrics) >= 7 else service_metrics
            )
            last_week = (
                service_metrics[-7:] if len(service_metrics) >= 7 else service_metrics
            )

            first_avg_wait = sum(m.avg_waiting_time for m in first_week) / len(
                first_week
            )
            last_avg_wait = sum(m.avg_waiting_time for m in last_week) / len(last_week)

            first_completion = sum(m.completion_rate for m in first_week) / len(
                first_week
            )
            last_completion = sum(m.completion_rate for m in last_week) / len(last_week)

            trends[service.id] = {
                "service_name": service.name,
                "wait_time_trend": self._calculate_trend_direction(
                    first_avg_wait, last_avg_wait
                ),
                "completion_trend": self._calculate_trend_direction(
                    first_completion, last_completion
                ),
                "total_tickets_period": sum(m.total_tickets for m in service_metrics),
                "avg_satisfaction": (
                    sum(
                        m.satisfaction_rate
                        for m in service_metrics
                        if m.satisfaction_rate > 0
                    )
                    / len([m for m in service_metrics if m.satisfaction_rate > 0])
                    if service_metrics
                    else 0
                ),
            }

        return {
            "period_days": days_back,
            "services_analyzed": len(trends),
            "trends": trends,
        }

    def _calculate_trend_direction(self, old_value, new_value):
        """Calculer la direction de la tendance"""
        if old_value == 0:
            return "new" if new_value > 0 else "stable"

        change_percent = ((new_value - old_value) / old_value) * 100

        if abs(change_percent) < 5:
            return "stable"
        elif change_percent > 0:
            return "increasing"
        else:
            return "decreasing"


# Optimisations base de données
class QueueOptimizations(models.Model):
    _name = "queue.optimizations"
    _description = "Optimisations Système"

    @api.model
    def create_database_indexes(self):
        """Créer des index pour optimiser les performances"""

        indexes_to_create = [
            # Index sur les tickets pour les requêtes fréquentes
            ("queue_ticket_service_state_idx", "queue_ticket", ["service_id", "state"]),
            ("queue_ticket_created_time_idx", "queue_ticket", ["created_time"]),
            (
                "queue_ticket_number_service_idx",
                "queue_ticket",
                ["ticket_number", "service_id"],
            ),
            # Index sur les services
            ("queue_service_active_open_idx", "queue_service", ["active", "is_open"]),
        ]

        for index_name, table_name, columns in indexes_to_create:
            try:
                self.env.cr.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {index_name} 
                    ON {table_name} ({', '.join(columns)})
                """
                )
                _logger.info(f"Index créé: {index_name}")
            except Exception as e:
                _logger.warning(f"Impossible de créer l'index {index_name}: {e}")

    @api.model
    def analyze_query_performance(self):
        """Analyser les performances des requêtes"""

        # Requêtes à analyser
        test_queries = [
            (
                "Dashboard data",
                "SELECT COUNT(*) FROM queue_ticket WHERE state = 'waiting'",
            ),
            (
                "Service stats",
                "SELECT service_id, COUNT(*) FROM queue_ticket WHERE created_time >= CURRENT_DATE GROUP BY service_id",
            ),
            (
                "Waiting tickets",
                "SELECT * FROM queue_ticket WHERE state = 'waiting' ORDER BY ticket_number LIMIT 10",
            ),
        ]

        performance_results = []

        for query_name, query in test_queries:
            try:
                import time

                start_time = time.time()

                self.env.cr.execute(query)
                results = self.env.cr.fetchall()

                end_time = time.time()
                execution_time = (end_time - start_time) * 1000  # en ms

                performance_results.append(
                    {
                        "query": query_name,
                        "execution_time_ms": round(execution_time, 2),
                        "rows_returned": len(results),
                        "status": (
                            "fast"
                            if execution_time < 100
                            else "slow" if execution_time < 500 else "very_slow"
                        ),
                    }
                )

            except Exception as e:
                performance_results.append(
                    {"query": query_name, "error": str(e), "status": "error"}
                )

        return performance_results

    @api.model
    def optimize_database_maintenance(self):
        """Optimiser la base de données"""

        optimizations = []

        try:
            # 1. VACUUM et ANALYZE sur les tables principales
            tables_to_optimize = ["queue_ticket", "queue_service"]

            for table in tables_to_optimize:
                self.env.cr.execute(f"VACUUM ANALYZE {table}")
                optimizations.append(f"Table {table} optimisée")

            # 2. Mise à jour des statistiques PostgreSQL
            self.env.cr.execute("ANALYZE")
            optimizations.append("Statistiques PostgreSQL mises à jour")

            # 3. Vérifier les index manquants
            self.create_database_indexes()
            optimizations.append("Index vérifiés/créés")

            _logger.info(f"Optimisation BD terminée: {optimizations}")

            return {
                "success": True,
                "optimizations": optimizations,
                "timestamp": fields.Datetime.now(),
            }

        except Exception as e:
            _logger.error(f"Erreur optimisation BD: {e}")
            return {"success": False, "error": str(e)}


# Mixin pour optimiser les requêtes
class QueueQueryOptimizationMixin(models.AbstractModel):
    _name = "queue.query.mixin"
    _description = "Mixin pour optimiser les requêtes"

    @api.model
    def search_optimized(self, domain, limit=None, order=None, count=False):
        """Version optimisée de search avec cache intelligent"""

        # Générer une clé de cache basée sur le domain
        cache_key = f"search_{self._name}_{hash(str(sorted(domain)))}"

        # Vérifier le cache (seulement pour les requêtes read-only)
        if not count and self.env.context.get("use_query_cache", False):
            cached_result = tools.config.get(cache_key)
            if cached_result:
                return cached_result

        # Exécuter la requête normale
        result = super().search(domain, limit=limit, order=order, count=count)

        # Mettre en cache si approprié
        if not count and len(result) < 1000:  # Éviter de cacher de gros résultats
            tools.config[cache_key] = result

        return result


# Décorateur pour mesurer les performances
def performance_monitor(func):
    """Décorateur pour monitorer les performances des méthodes"""

    def wrapper(self, *args, **kwargs):
        import time

        start_time = time.time()

        try:
            result = func(self, *args, **kwargs)
            execution_time = (time.time() - start_time) * 1000

            if execution_time > 1000:  # Plus d'1 seconde
                _logger.warning(
                    f"Méthode lente détectée: {func.__name__} - {execution_time:.2f}ms"
                )

            return result

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            _logger.error(
                f"Erreur dans {func.__name__} après {execution_time:.2f}ms: {e}"
            )
            raise

    return wrapper


# Classe pour les alertes système
class QueueSystemAlerts(models.Model):
    _name = "queue.system.alerts"
    _description = "Alertes Système"
    _order = "create_date desc"

    name = fields.Char("Titre", required=True)
    message = fields.Text("Message", required=True)
    alert_type = fields.Selection(
        [
            ("info", "Information"),
            ("warning", "Avertissement"),
            ("error", "Erreur"),
            ("critical", "Critique"),
        ],
        string="Type",
        required=True,
        default="info",
    )

    service_id = fields.Many2one("queue.service", "Service Concerné")
    is_resolved = fields.Boolean("Résolu", default=False)
    resolved_date = fields.Datetime("Date de Résolution")
    resolved_by = fields.Many2one("res.users", "Résolu par")

    @api.model
    def create_alert(self, title, message, alert_type="info", service_id=None):
        """Créer une nouvelle alerte"""
        return self.create(
            {
                "name": title,
                "message": message,
                "alert_type": alert_type,
                "service_id": service_id,
            }
        )

    def resolve_alert(self):
        """Résoudre une alerte"""
        self.write(
            {
                "is_resolved": True,
                "resolved_date": fields.Datetime.now(),
                "resolved_by": self.env.user.id,
            }
        )

    @api.model
    def check_system_alerts(self):
        """Vérifier et créer des alertes système automatiques"""
        service_model = self.env["queue.service"]
        services = service_model.search([("active", "=", True)])

        for service in services:
            waiting_count = len(service.waiting_ticket_ids)

            # Alerte file d'attente trop longue
            if waiting_count > 20:
                existing_alert = self.search(
                    [
                        ("service_id", "=", service.id),
                        ("alert_type", "=", "critical"),
                        ("is_resolved", "=", False),
                        ("name", "like", "File d'attente critique"),
                    ]
                )

                if not existing_alert:
                    self.create_alert(
                        f"File d'attente critique - {service.name}",
                        f"Le service {service.name} a {waiting_count} personnes en attente. Action immédiate requise.",
                        "critical",
                        service.id,
                    )

        return True
