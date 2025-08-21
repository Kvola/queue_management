# ==============================================================================
# AMÉLIORATION DE LA GESTION D'ANNULATION DES TICKETS
# ==============================================================================

# 1. MODÈLE - Améliorations dans models/queue_ticket.py
# ==============================================================================
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError, AccessError
from datetime import datetime, timedelta
import logging
import random
import string
import hashlib

_logger = logging.getLogger(__name__)

class QueueTicket(models.Model):
    _name = "queue.ticket"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Ticket de File d'Attente"
    _order = "ticket_number desc"
    _rec_name = "display_name"

    # Informations de base
    service_id = fields.Many2one(
        "queue.service", "Service", required=True, ondelete="cascade"
    )
    ticket_number = fields.Integer("Numéro de Ticket", required=True)
    display_name = fields.Char(
        "Nom d'affichage", compute="_compute_display_name", store=True
    )

    # Informations client
    customer_name = fields.Char("Nom du Client")
    customer_phone = fields.Char("Téléphone")
    customer_email = fields.Char("Email")

    # États et timing
    state = fields.Selection(
        [
            ("waiting", "En Attente"),
            ("called", "Appelé"),
            ("serving", "En Service"),
            ("served", "Servi"),
            ("cancelled", "Annulé"),
            ("no_show", "Absent"),
        ],
        string="État",
        default="waiting",
        tracking=True,
    )

    priority = fields.Selection(
        [("normal", "Normal"), ("high", "Priorité"), ("urgent", "Urgent")],
        string="Priorité",
        default="normal",
    )

    # Timestamps
    created_time = fields.Datetime("Heure de Création", default=fields.Datetime.now)
    called_time = fields.Datetime("Heure d'Appel")
    served_time = fields.Datetime("Heure de Service")
    completed_time = fields.Datetime("Heure de Fin")

    # Calculs
    waiting_time = fields.Float(
        "Temps d'Attente (min)", compute="_compute_waiting_time", store=True
    )
    service_time = fields.Float(
        "Temps de Service (min)", compute="_compute_service_time", store=True
    )
    estimated_wait_time = fields.Float(
        "Temps d'attente estimé", compute="_compute_estimated_wait", store=True
    )

    # Autres
    notes = fields.Text("Notes")
    notification_sent = fields.Boolean("Notification envoyée", default=False)
    qr_code = fields.Char("Code QR", compute="_compute_qr_code", store=True)
    rating = fields.Selection(
        [
            ("1", "⭐"),
            ("2", "⭐⭐"),
            ("3", "⭐⭐⭐"),
            ("4", "⭐⭐⭐⭐"),
            ("5", "⭐⭐⭐⭐⭐"),
        ],
        string="Évaluation",
    )
    feedback = fields.Text("Commentaires")
    # Nouveaux champs pour l'annulation améliorée
    cancellation_reason = fields.Text("Raison d'annulation", tracking=True)
    cancelled_by = fields.Many2one("res.users", "Annulé par", tracking=True)
    cancelled_time = fields.Datetime("Heure d'annulation", tracking=True)
    cancellation_type = fields.Selection(
        [
            ("client", "Annulation client"),
            ("agent", "Annulation agent"),
            ("system", "Annulation système"),
            ("timeout", "Timeout"),
        ],
        string="Type d'annulation",
        tracking=True,
    )

    # Système de verrouillage pour éviter les doubles annulations
    cancellation_lock = fields.Boolean("Verrouillage annulation", default=False)

    # Historique des actions sur le ticket
    action_history = fields.Text("Historique des actions", default="")

    # Nouveau champ pour la référence unique
    ticket_reference = fields.Char(
        "Référence Ticket",
        size=20,
        required=True,
        index=True,
        copy=False,
        help="Référence unique du ticket (ex: QUE-2025-001234)",
    )

    # Référence courte pour affichage (QR code, SMS)
    short_reference = fields.Char(
        "Référence Courte",
        size=8,
        index=True,
        copy=False,
        help="Référence courte (ex: QUE12AB)",
    )

    # Hash unique pour sécurité
    security_hash = fields.Char(
        "Hash Sécurisé",
        size=32,
        index=True,
        copy=False,
        help="Hash MD5 pour validation sécurisée",
    )

    # Date du feedback
    feedback_time = fields.Datetime(
        string="Date du Feedback", help="Date et heure de soumission du feedback"
    )

    # Statut du feedback
    feedback_status = fields.Selection(
        [("pending", "En attente"), ("submitted", "Soumis"), ("reviewed", "Examiné")],
        string="Statut Feedback",
        default="pending",
    )

    # Champs calculés pour les statistiques
    rating_numeric = fields.Float(
        string="Note Numérique",
        compute="_compute_rating_numeric",
        store=True,
        help="Conversion de la note en valeur numérique pour les calculs",
    )

    is_feedback_eligible = fields.Boolean(
        string="Éligible pour Feedback",
        compute="_compute_feedback_eligible",
        help="Détermine si le ticket peut recevoir un feedback",
    )

    has_feedback = fields.Boolean(
        string="A un Feedback",
        compute="_compute_has_feedback",
        store=True,
        help="Indique si le ticket a reçu un feedback",
    )

    # ========================================
    # MÉTHODES DE CALCUL
    # ========================================

    @api.depends("rating")
    def _compute_rating_numeric(self):
        """Convertir la note en valeur numérique"""
        for ticket in self:
            if ticket.rating:
                try:
                    ticket.rating_numeric = float(ticket.rating)
                except (ValueError, TypeError):
                    ticket.rating_numeric = 0.0
            else:
                ticket.rating_numeric = 0.0

    @api.depends("state")
    def _compute_feedback_eligible(self):
        """Détermine si le ticket est éligible pour un feedback"""
        for ticket in self:
            # Seuls les tickets servis peuvent recevoir un feedback
            ticket.is_feedback_eligible = ticket.state == "served"

    @api.depends("rating", "feedback")
    def _compute_has_feedback(self):
        """Détermine si le ticket a un feedback"""
        for ticket in self:
            ticket.has_feedback = bool(ticket.rating and int(ticket.rating) > 0)

    # ========================================
    # MÉTHODES MÉTIER POUR LE FEEDBACK
    # ========================================

    def submit_feedback(self, rating, feedback_text=""):
        """Soumettre un feedback pour le ticket"""
        self.ensure_one()

        # Vérifications
        if not self.is_feedback_eligible:
            raise ValueError("Ce ticket n'est pas éligible pour un feedback")

        if self.has_feedback:
            raise ValueError("Un feedback a déjà été soumis pour ce ticket")

        if not rating or int(rating) < 1 or int(rating) > 5:
            raise ValueError("La note doit être comprise entre 1 et 5")

        # Enregistrement
        vals = {
            "rating": str(rating),
            "feedback": feedback_text[:1000] if feedback_text else "",
            "feedback_time": fields.Datetime.now(),
            "feedback_status": "submitted",
        }

        self.write(vals)

        # Log
        _logger.info(
            f"Feedback soumis pour ticket {self.ticket_reference or f'#{self.ticket_number}'}: {rating}/5"
        )

        return True

    def can_submit_feedback(self):
        """Vérifier si un feedback peut être soumis"""
        self.ensure_one()
        return self.is_feedback_eligible and not self.has_feedback

    def get_feedback_url(self):
        """Obtenir l'URL de feedback pour le ticket"""
        self.ensure_one()

        if hasattr(self, "ticket_reference") and self.ticket_reference:
            return f"/queue/feedback/{self.ticket_reference}"
        else:
            return f"/queue/feedback/ticket/{self.id}"

    # ========================================
    # MÉTHODES DE RECHERCHE ET FILTRAGE
    # ========================================

    @api.model
    def get_feedback_statistics(self, domain=None):
        """Obtenir les statistiques de feedback"""
        if domain is None:
            domain = []

        # Ajouter le filtre pour les tickets avec feedback
        feedback_domain = domain + [("rating", ">", 0)]

        tickets_with_feedback = self.search(feedback_domain)

        if not tickets_with_feedback:
            return {
                "total_count": 0,
                "avg_rating": 0,
                "rating_distribution": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                "satisfaction_rate": 0,
                "feedback_rate": 0,
            }

        # Calculer les statistiques
        ratings = [int(t.rating) for t in tickets_with_feedback if t.rating]

        rating_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for rating in ratings:
            if rating in rating_distribution:
                rating_distribution[rating] += 1

        # Calculer les moyennes
        total_count = len(ratings)
        avg_rating = sum(ratings) / total_count if total_count > 0 else 0

        # Taux de satisfaction (tickets avec feedback positif)
        satisfied_tickets = [t for t in tickets_with_feedback if int(t.rating) > 3]
        satisfaction_rate = (
            len(satisfied_tickets) / total_count * 100 if total_count > 0 else 0
        )

        # Taux de feedback (tickets ayant reçu un feedback)
        feedback_rate = (
            total_count / self.search_count(domain) * 100
            if self.search_count(domain) > 0
            else 0
        )

        return {
            "total_count": total_count,
            "avg_rating": avg_rating,
            "rating_distribution": rating_distribution,
            "satisfaction_rate": satisfaction_rate,
            "feedback_rate": feedback_rate,
        }

    @api.model
    def create(self, vals):
        """Override create pour générer les références uniques"""

        # Générer le ticket_number s'il n'existe pas déjà
        if "ticket_number" not in vals or not vals.get("ticket_number"):
            service_id = vals.get("service_id")
            if not service_id:
                raise ValidationError("Service requis pour créer un ticket")

            service = self.env["queue.service"].browse(service_id)
            if not service.exists():
                raise ValidationError("Service non trouvé")

            vals["ticket_number"] = self._generate_next_ticket_number(service)

        # Générer la référence unique AVANT la création
        if "ticket_reference" not in vals:
            vals["ticket_reference"] = self._generate_unique_reference(vals)

        # Générer la référence courte
        if "short_reference" not in vals:
            vals["short_reference"] = self._generate_short_reference(vals)

        # Créer le ticket
        ticket = super(QueueTicket, self).create(vals)

        # Générer le hash sécurisé APRÈS création (car on a besoin de l'ID)
        ticket.security_hash = ticket._generate_security_hash()

        # Ajouter à l'historique
        ticket._add_action_history(
            "created", f"Ticket créé avec référence {ticket.ticket_reference}"
        )

        # Calculer le temps d'attente estimé après création
        ticket._compute_estimated_wait()

        return ticket

    def _generate_unique_reference(self, vals):
        """
        OPTION 1: Référence séquentielle intelligente
        Format: [PREFIX]-[ANNÉE]-[NUMÉRO_SÉQUENCE]
        Exemple: QUE-2025-001234
        """
        try:
            # Prefix du service ou global
            service_id = vals.get("service_id")
            if service_id:
                service = self.env["queue.service"].browse(service_id)
                prefix = (
                    service.code[:3].upper()
                    if hasattr(service, "code") and service.code
                    else "QUE"
                )
            else:
                prefix = "QUE"

            # Année courante
            current_year = datetime.now().year

            # Obtenir le prochain numéro de séquence pour cette année
            sequence_number = self._get_next_sequence_number(prefix, current_year)

            # Format final
            reference = f"{prefix}-{current_year}-{sequence_number:06d}"

            # Vérifier l'unicité (sécurité)
            if self.search([("ticket_reference", "=", reference)], limit=1):
                # Fallback si collision (très rare)
                reference = f"{prefix}-{current_year}-{sequence_number:06d}-{random.randint(10,99)}"

            return reference

        except Exception as e:
            _logger.error(f"Erreur génération référence unique: {e}")
            # Fallback d'urgence
            return f"QUE-{datetime.now().year}-{random.randint(100000, 999999)}"

    def _get_next_sequence_number(self, prefix, year):
        """Obtenir le prochain numéro de séquence pour l'année"""
        try:
            # Chercher la dernière référence de cette année avec ce préfixe
            last_ticket = self.search(
                [("ticket_reference", "like", f"{prefix}-{year}-%")],
                order="ticket_reference desc",
                limit=1,
            )

            if last_ticket:
                # Extraire le numéro de séquence
                parts = last_ticket.ticket_reference.split("-")
                if len(parts) >= 3:
                    try:
                        last_sequence = int(
                            parts[2].split("-")[0]
                        )  # Au cas où il y aurait un suffixe
                        return last_sequence + 1
                    except ValueError:
                        pass

            # Premier ticket de l'année
            return 1

        except Exception as e:
            _logger.error(f"Erreur récupération séquence: {e}")
            return random.randint(1, 1000)

    def _generate_short_reference(self, vals):
        """
        OPTION 2: Référence courte alphanumériques
        Format: [PREFIX][CHIFFRES][LETTRES] - 8 caractères max
        Exemple: QUE12AB, SRV34XY
        """
        try:
            service_id = vals.get("service_id")
            if service_id:
                service = self.env["queue.service"].browse(service_id)
                prefix = (
                    service.code[:3].upper()
                    if hasattr(service, "code") and service.code
                    else "QUE"
                )
            else:
                prefix = "QUE"

            # Générer partie numérique (2 chiffres)
            ticket_number = vals.get("ticket_number", 1)
            numeric_part = f"{ticket_number % 100:02d}"

            # Générer partie alphabétique (2 lettres)
            alphabet = string.ascii_uppercase
            alpha_part = "".join(random.choices(alphabet, k=2))

            short_ref = f"{prefix[:3]}{numeric_part}{alpha_part}"

            # Vérifier unicité
            attempt = 0
            while (
                self.search([("short_reference", "=", short_ref)], limit=1)
                and attempt < 10
            ):
                alpha_part = "".join(random.choices(alphabet, k=2))
                short_ref = f"{prefix[:3]}{numeric_part}{alpha_part}"
                attempt += 1

            return short_ref

        except Exception as e:
            _logger.error(f"Erreur génération référence courte: {e}")
            return f"QUE{random.randint(10,99)}{random.choices(string.ascii_uppercase, k=2)}"

    def _generate_security_hash(self):
        """
        OPTION 3: Hash sécurisé pour validation
        Combine ID + référence + timestamp
        """
        try:
            data_to_hash = f"{self.id}_{self.ticket_reference}_{self.create_date}_{self.service_id.id}"
            return hashlib.md5(data_to_hash.encode()).hexdigest()
        except Exception as e:
            _logger.error(f"Erreur génération hash: {e}")
            return hashlib.md5(f"fallback_{self.id}".encode()).hexdigest()

    # ========================================
    # OPTION 4: RÉFÉRENCE UUID (ALTERNATIVE)
    # ========================================

    uuid_reference = fields.Char(
        "UUID Reference",
        size=36,
        copy=False,
        help="UUID unique pour intégrations externes",
    )

    def _generate_uuid_reference(self):
        """Générer une référence UUID (pour intégrations externes)"""
        return str(uuid.uuid4())

    # ========================================
    # MÉTHODES DE VALIDATION ET RECHERCHE
    # ========================================

    @api.model
    def find_ticket_by_reference(self, reference, reference_type="main"):
        """
        Trouver un ticket par sa référence

        Args:
            reference (str): La référence à rechercher
            reference_type (str): Type de référence ('main', 'short', 'hash')

        Returns:
            recordset: Le ticket trouvé ou vide
        """
        try:
            if reference_type == "main":
                return self.search([("ticket_reference", "=", reference)], limit=1)
            elif reference_type == "short":
                return self.search(
                    [("short_reference", "=", reference.upper())], limit=1
                )
            elif reference_type == "hash":
                return self.search([("security_hash", "=", reference)], limit=1)
            else:
                # Recherche flexible
                ticket = self.search(
                    [("ticket_reference", "=", reference)], limit=1
                ) or self.search([("short_reference", "=", reference.upper())], limit=1)
                return ticket

        except Exception as e:
            _logger.error(f"Erreur recherche ticket par référence: {e}")
            return self.browse()

    @api.model
    def validate_ticket_security(self, ticket_id, security_hash):
        """
        Valider un ticket avec son hash de sécurité

        Args:
            ticket_id (int): ID du ticket
            security_hash (str): Hash à valider

        Returns:
            bool: True si valide
        """
        try:
            ticket = self.browse(ticket_id)
            if not ticket.exists():
                return False

            return ticket.security_hash == security_hash

        except Exception as e:
            _logger.error(f"Erreur validation sécurité: {e}")
            return False

    # ========================================
    # MÉTHODES WEB AMÉLIORÉES AVEC RÉFÉRENCES
    # ========================================

    @api.model
    def get_ticket_by_reference_web(self, reference):
        """
        Version web pour récupérer un ticket par référence

        Args:
            reference (str): Référence principale ou courte

        Returns:
            dict: Informations du ticket ou erreur
        """
        try:
            # Essayer de trouver le ticket
            ticket = self.find_ticket_by_reference(reference)

            if not ticket:
                # Essayer avec la référence courte
                ticket = self.find_ticket_by_reference(reference, "short")

            if not ticket:
                return {
                    "success": False,
                    "error": "Ticket non trouvé avec cette référence",
                }

            # Retourner les informations complètes
            position = 0
            if ticket.state == "waiting":
                position = ticket.get_queue_position()

            return {
                "success": True,
                "ticket": {
                    "id": ticket.id,
                    "ticket_number": ticket.ticket_number,
                    "ticket_reference": ticket.ticket_reference,
                    "short_reference": ticket.short_reference,
                    "state": ticket.state,
                    "position": position,
                    "estimated_wait_time": ticket.estimated_wait_time,
                    "service_name": ticket.service_id.name,
                    "created_time": (
                        ticket.created_time.strftime("%d/%m/%Y %H:%M")
                        if ticket.created_time
                        else ""
                    ),
                    "can_cancel": ticket.state in ["waiting", "called"],
                    "security_hash": ticket.security_hash,  # Pour validation côté client
                },
            }

        except Exception as e:
            _logger.error(f"Erreur get_ticket_by_reference_web: {e}")
            return {"success": False, "error": "Erreur lors de la recherche"}

    def cancel_ticket_by_reference_web(self, reference, reason="", security_hash=""):
        """Annuler un ticket par référence unique depuis l'interface web"""
        try:
            # Recherche du ticket
            ticket = self.find_ticket_by_reference(reference)
            if not ticket:
                ticket = self.find_ticket_by_reference(reference, "short")

            if not ticket:
                return {
                    "success": False,
                    "error": f"Ticket avec référence {reference} non trouvé",
                }

            # Vérifications de sécurité
            if ticket.state not in ["waiting", "called"]:
                state_labels = {
                    "served": "déjà servi",
                    "cancelled": "déjà annulé",
                    "no_show": "marqué comme absent",
                }
                return {
                    "success": False,
                    "error": f'Ce ticket est {state_labels.get(ticket.state, "non annulable")}',
                }

            # Vérifier le hash de sécurité si présent
            if hasattr(ticket, "security_hash") and ticket.security_hash:
                if security_hash != ticket.security_hash:
                    return {"success": False, "error": "Code de sécurité invalide"}

            # Effectuer l'annulation
            old_state = ticket.state
            ticket.write(
                {
                    "state": "cancelled",
                    "cancelled_time": fields.Datetime.now(),
                    "cancellation_reason": reason[:500] if reason else "",
                }
            )

            # Log de l'action
            _logger.info(
                f"Ticket {ticket.id} (ref: {reference}) annulé via web - état précédent: {old_state}"
            )

            return {
                "success": True,
                "message": f"Ticket #{ticket.ticket_number} annulé avec succès",
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "service_name": ticket.service_id.name,
            }

        except Exception as e:
            _logger.error(f"Erreur cancel_ticket_by_reference_web {reference}: {e}")
            return {"success": False, "error": "Erreur technique lors de l'annulation"}

    # ========================================
    # INTÉGRATION QR CODE AMÉLIORÉE
    # ========================================

    @api.depends("service_id", "ticket_reference", "short_reference")
    def _compute_qr_code(self):
        """QR Code amélioré avec références uniques"""
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        for ticket in self:
            if ticket.ticket_reference:
                # URL avec référence unique (plus sûr)
                url = f"{base_url}/queue/track/{ticket.ticket_reference}"
                ticket.qr_code = url
            elif ticket.service_id and ticket.ticket_number:
                # Fallback vers l'ancienne méthode
                url = f"{base_url}/queue/my_ticket/{ticket.ticket_number}/{ticket.service_id.id}"
                ticket.qr_code = url
            else:
                ticket.qr_code = False

    # ========================================
    # UTILITAIRES ET MAINTENANCE
    # ========================================

    @api.model
    def generate_missing_references(self):
        """
        Générer les références manquantes pour les tickets existants
        (Utilitaire pour migration)
        """
        tickets_without_ref = self.search([("ticket_reference", "=", False)])

        count = 0
        for ticket in tickets_without_ref:
            try:
                # Recréer les références
                vals = {
                    "service_id": ticket.service_id.id,
                    "ticket_number": ticket.ticket_number,
                }

                ticket.ticket_reference = self._generate_unique_reference(vals)
                ticket.short_reference = self._generate_short_reference(vals)
                ticket.security_hash = ticket._generate_security_hash()

                count += 1

            except Exception as e:
                _logger.error(f"Erreur génération référence ticket {ticket.id}: {e}")

        _logger.info(f"Références générées pour {count} tickets")
        return count

    @api.model
    def check_reference_uniqueness(self):
        """Vérifier l'unicité des références (maintenance)"""
        # Vérifier les doublons de références principales
        duplicates = self.read_group(
            [],
            ["ticket_reference"],
            ["ticket_reference"],
            having=[("ticket_reference_count", ">", 1)],
        )

        issues = []
        for dup in duplicates:
            ref = dup["ticket_reference"]
            tickets = self.search([("ticket_reference", "=", ref)])
            issues.append(
                {"reference": ref, "count": len(tickets), "ticket_ids": tickets.ids}
            )

        if issues:
            _logger.warning(f"Doublons de références détectés: {len(issues)}")

        return {"duplicate_references": len(issues), "issues": issues}

    @api.model
    def auto_cancel_timeout_tickets(self, timeout_minutes=15):
        timeout_date = datetime.now() - timedelta(minutes=timeout_minutes)
        timeout_tickets = self.search(
            [("state", "=", "called"), ("called_time", "<", timeout_date)]
        )
        for ticket in timeout_tickets:
            try:
                ticket.action_cancel_ticket_v2(
                    reason=f"Timeout automatique après {timeout_minutes} minutes sans réponse",
                    cancellation_type="timeout",
                )
                _logger.info(f"Ticket #{ticket.ticket_number} annulé par timeout")
            except Exception as e:
                _logger.error(f"Erreur timeout ticket #{ticket.ticket_number}: {e}")

    @api.model
    def scheduled_cleanup_and_maintenance(self):
        cleanup_result = self.cleanup_old_cancelled_tickets(days_to_keep=30)
        _logger.info(f"Nettoyage effectué: {cleanup_result} tickets supprimés")

        maintenance_result = self.scheduled_data_maintenance()
        _logger.info(f"Maintenance des données: {maintenance_result}")

    @api.model
    def scheduled_update_estimated_times(self):
        waiting_tickets = self.search([("state", "=", "waiting")])
        if waiting_tickets:
            waiting_tickets._compute_estimated_wait()
            _logger.info(
                f"Temps d'attente mis à jour pour {len(waiting_tickets)} tickets"
            )

    priority_badge = fields.Html(compute="_compute_priority_badge", sanitize=False)

    @api.depends("priority")
    def _compute_priority_badge(self):
        for rec in self:
            if rec.priority == "urgent":
                badge = '<span class="badge badge-danger">URGENT</span>'
            elif rec.priority == "high":
                badge = '<span class="badge badge-warning">PRIORITÉ</span>'
            else:
                badge = '<span class="badge badge-secondary">NORMAL</span>'
            rec.priority_badge = badge

    def get_queue_position(self):
        all_waiting = (
            self.env["queue.ticket"]
            .sudo()
            .search(
                [("service_id", "=", self.service_id.id), ("state", "=", "waiting")],
                order="create_date asc",
            )
        )

        for index, t in enumerate(all_waiting):
            if t.id == self.id:
                return index + 1
        return 0

    def _add_action_history(self, action_type, description, user_id=None):
        """Ajouter une action à l'historique"""
        if not user_id:
            user_id = self.env.user.id

        timestamp = fields.Datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        user_name = self.env["res.users"].browse(user_id).name

        new_entry = (
            f"[{timestamp}] {action_type.upper()}: {description} (par {user_name})"
        )

        if self.action_history:
            self.action_history = f"{self.action_history}\n{new_entry}"
        else:
            self.action_history = new_entry

    def action_cancel_ticket_v2(
        self, reason=None, cancellation_type="client", force=False
    ):
        """
        Version améliorée de l'annulation avec gestion des erreurs robuste

        Args:
            reason (str): Raison de l'annulation
            cancellation_type (str): Type d'annulation
            force (bool): Forcer l'annulation même si verrouillé

        Returns:
            dict: Résultat de l'opération
        """
        self.ensure_one()

        try:
            # 1. Vérifications préliminaires
            validation_result = self._validate_cancellation(force)
            if not validation_result["success"]:
                return validation_result

            # 2. Acquisition du verrou
            lock_result = self._acquire_cancellation_lock()
            if not lock_result["success"]:
                return lock_result

            try:
                # 3. Effectuer l'annulation
                cancel_result = self._execute_cancellation(reason, cancellation_type)
                if not cancel_result["success"]:
                    return cancel_result

                # 4. Actions post-annulation
                self._post_cancellation_actions(reason, cancellation_type)

                return {
                    "success": True,
                    "message": f"Ticket #{self.ticket_number} annulé avec succès",
                    "ticket_id": self.id,
                    "new_state": "cancelled",
                }

            finally:
                # 5. Libérer le verrou (dans tous les cas)
                self._release_cancellation_lock()

        except Exception as e:
            _logger.error(
                f"Erreur critique annulation ticket #{self.ticket_number}: {e}"
            )
            return {"success": False, "error": "Erreur système lors de l'annulation"}

    def _validate_cancellation(self, force=False):
        """Valider si le ticket peut être annulé"""
        try:
            # Vérifier l'état du ticket
            if self.state not in ["waiting", "called"]:
                state_labels = {
                    "serving": "en cours de service",
                    "served": "déjà terminé",
                    "cancelled": "déjà annulé",
                    "no_show": "marqué comme absent",
                }
                current_state = state_labels.get(self.state, self.state)
                return {
                    "success": False,
                    "error": f"Impossible d'annuler un ticket {current_state}",
                }

            # Vérifier le verrouillage (sauf si force=True)
            if not force and self.cancellation_lock:
                return {
                    "success": False,
                    "error": "Ticket en cours d'annulation par un autre processus",
                }

            # Vérifications métier supplémentaires
            config = self.env["ir.config_parameter"].sudo()

            # Délai maximum pour annulation client
            if (
                hasattr(self, "cancellation_type")
                and self.cancellation_type == "client"
            ):
                max_delay = int(
                    config.get_param("queue.max_cancellation_delay_minutes", 30)
                )
                if self.created_time:
                    time_elapsed = (
                        fields.Datetime.now() - self.created_time
                    ).total_seconds() / 60
                    if time_elapsed > max_delay:
                        return {
                            "success": False,
                            "error": f"Délai d'annulation dépassé ({max_delay} minutes max)",
                        }

            # Vérifier si les annulations sont autorisées
            allow_cancellation = (
                config.get_param("queue.allow_ticket_cancellation", "True").lower()
                == "true"
            )
            if not allow_cancellation and not force:
                return {
                    "success": False,
                    "error": "Les annulations de tickets sont temporairement désactivées",
                }

            return {"success": True}

        except Exception as e:
            _logger.error(f"Erreur validation annulation: {e}")
            return {"success": False, "error": "Erreur lors de la validation"}

    def _acquire_cancellation_lock(self):
        """Acquérir le verrou d'annulation"""
        try:
            # Vérifier si déjà verrouillé
            self.env.cr.execute(
                "SELECT cancellation_lock FROM queue_ticket WHERE id = %s FOR UPDATE NOWAIT",
                (self.id,),
            )
            result = self.env.cr.fetchone()

            if result and result[0]:
                return {
                    "success": False,
                    "error": "Ticket en cours de traitement par un autre utilisateur",
                }

            # Acquérir le verrou
            self.env.cr.execute(
                "UPDATE queue_ticket SET cancellation_lock = true WHERE id = %s",
                (self.id,),
            )

            return {"success": True}

        except Exception as e:
            _logger.error(f"Erreur acquisition verrou: {e}")
            return {"success": False, "error": "Impossible de verrouiller le ticket"}

    def _execute_cancellation(self, reason, cancellation_type):
        """Exécuter l'annulation proprement dite"""
        try:
            # Préparer les valeurs
            cancellation_data = {
                "state": "cancelled",
                "cancelled_time": fields.Datetime.now(),
                "cancelled_by": self.env.user.id,
                "cancellation_type": cancellation_type,
                "cancellation_reason": reason or "Aucune raison spécifiée",
            }

            # Mettre à jour avec validation
            self.with_context(skip_validation=True).write(cancellation_data)

            # Ajouter à l'historique
            self._add_action_history(
                "cancelled",
                f"Ticket annulé - Type: {cancellation_type} - Raison: {reason}",
            )

            # Commit de la transaction pour sécuriser
            self.env.cr.commit()

            return {"success": True}

        except Exception as e:
            # Rollback en cas d'erreur
            self.env.cr.rollback()
            _logger.error(f"Erreur exécution annulation: {e}")
            return {
                "success": False,
                "error": "Erreur lors de l'enregistrement de l'annulation",
            }

    def _release_cancellation_lock(self):
        """Libérer le verrou d'annulation"""
        try:
            self.env.cr.execute(
                "UPDATE queue_ticket SET cancellation_lock = false WHERE id = %s",
                (self.id,),
            )
        except Exception as e:
            _logger.error(f"Erreur libération verrou: {e}")

    def _post_cancellation_actions(self, reason, cancellation_type):
        """Actions à effectuer après annulation"""
        try:
            # 1. Notification client
            self._notify_cancellation(reason, cancellation_type)

            # 2. Mise à jour des statistiques du service
            self.service_id._update_cancellation_stats()

            # 3. Log pour audit
            _logger.info(
                f"Ticket #{self.ticket_number} annulé - "
                f"Service: {self.service_id.name} - "
                f"Type: {cancellation_type} - "
                f"Utilisateur: {self.env.user.name}"
            )

            # 4. Message de suivi Odoo
            self.message_post(
                body=f"Ticket annulé ({cancellation_type})",
                subject=f"Annulation ticket #{self.ticket_number}",
                message_type="notification",
            )

        except Exception as e:
            # Ne pas faire échouer l'annulation pour ces actions
            _logger.warning(f"Erreur actions post-annulation: {e}")

    def _notify_cancellation(self, reason, cancellation_type):
        """Notification améliorée d'annulation"""
        try:
            if not self.customer_email:
                return

            # Template personnalisé selon le type
            if cancellation_type == "client":
                subject = f"Confirmation d'annulation - Ticket #{self.ticket_number}"
                message = f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px;">
                    <h2 style="color: #28a745;">Annulation confirmée</h2>
                    <p>Votre ticket <strong>#{self.ticket_number}</strong> 
                    pour le service <strong>{self.service_id.name}</strong> 
                    a été annulé comme demandé.</p>
                    {f"<p><em>Raison: {reason}</em></p>" if reason else ""}
                    <p>Vous pouvez reprendre un nouveau ticket à tout moment.</p>
                </div>
                """
            else:
                subject = f"Ticket #{self.ticket_number} annulé"
                message = f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px;">
                    <h2 style="color: #dc3545;">Ticket annulé</h2>
                    <p>Votre ticket <strong>#{self.ticket_number}</strong> 
                    pour le service <strong>{self.service_id.name}</strong> 
                    a été annulé.</p>
                    {f"<p><em>Raison: {reason}</em></p>" if reason else ""}
                    <p>Veuillez nous excuser pour la gêne occasionnée.</p>
                </div>
                """

            # Envoyer l'email
            mail_values = {
                "subject": subject,
                "body_html": message,
                "email_to": self.customer_email,
                "auto_delete": True,
                "email_from": self.env.company.email or "noreply@example.com",
            }

            self.env["mail.mail"].sudo().create(mail_values).send()

        except Exception as e:
            _logger.error(f"Erreur notification annulation: {e}")

    def cancel_ticket_web_v2(self, data):
        """Version améliorée de l'annulation web avec validations renforcées"""
        try:
            ticket_number = data.get("ticket_number")
            service_id = data.get("service_id")
            reason = data.get("reason", "")
            security_hash = data.get("security_hash", "")

            if not ticket_number or not service_id:
                return {"success": False, "error": "Paramètres manquants"}

            # Recherche du ticket
            ticket = self.search(
                [
                    ("ticket_number", "=", ticket_number),
                    ("service_id", "=", service_id),
                ],
                limit=1,
            )

            if not ticket:
                return {"success": False, "error": "Ticket non trouvé"}

            # Vérifications
            if ticket.state not in ["waiting", "called"]:
                return {
                    "success": False,
                    "error": f"Ce ticket ne peut plus être annulé (état: {ticket.state})",
                }

            # Vérification du hash si présent
            if (
                hasattr(ticket, "security_hash")
                and ticket.security_hash
                and security_hash
            ):
                if security_hash != ticket.security_hash:
                    return {"success": False, "error": "Code de sécurité invalide"}

            # Annulation
            ticket.write(
                {
                    "state": "cancelled",
                    "cancelled_time": fields.Datetime.now(),
                    "cancellation_reason": reason[:500] if reason else "",
                }
            )

            return {
                "success": True,
                "message": f"Ticket #{ticket_number} annulé avec succès",
                "ticket_id": ticket.id,
            }

        except Exception as e:
            _logger.error(f"Erreur cancel_ticket_web_v2: {e}")
            return {"success": False, "error": "Erreur lors de l'annulation"}

    def can_be_cancelled(self):
        """Vérifier si le ticket peut être annulé"""
        self.ensure_one()
        return self.state in ["waiting", "called"]

    @api.model
    def bulk_cancel_tickets(self, ticket_ids, reason="Annulation en masse"):
        """Annuler plusieurs tickets en une fois"""
        try:
            tickets = self.browse(ticket_ids)
            cancellable_tickets = tickets.filtered("can_be_cancelled")

            if not cancellable_tickets:
                return {"success": False, "error": "Aucun ticket annulable sélectionné"}

            cancellable_tickets.write(
                {
                    "state": "cancelled",
                    "cancelled_time": fields.Datetime.now(),
                    "cancellation_reason": reason,
                }
            )

            return {
                "success": True,
                "cancelled_count": len(cancellable_tickets),
                "message": f"{len(cancellable_tickets)} tickets annulés",
            }

        except Exception as e:
            _logger.error(f"Erreur bulk_cancel_tickets: {e}")
            return {"success": False, "error": "Erreur lors de l'annulation en masse"}

    def get_cancellation_stats(self, date_from=None, date_to=None):
        """Obtenir les statistiques d'annulation"""
        domain = [("state", "=", "cancelled")]

        if date_from:
            domain.append(("cancelled_time", ">=", date_from))
        if date_to:
            domain.append(("cancelled_time", "<=", date_to))

        cancelled_tickets = self.search(domain)

        # Grouper par service
        services_stats = {}
        for ticket in cancelled_tickets:
            service_name = ticket.service_id.name
            if service_name not in services_stats:
                services_stats[service_name] = {"count": 0, "reasons": {}}

            services_stats[service_name]["count"] += 1

            reason = ticket.cancellation_reason or "Aucune raison"
            if reason not in services_stats[service_name]["reasons"]:
                services_stats[service_name]["reasons"][reason] = 0
            services_stats[service_name]["reasons"][reason] += 1

        return {
            "total_cancelled": len(cancelled_tickets),
            "by_service": services_stats,
            "period": {"from": date_from, "to": date_to},
        }

    @api.model
    def _validate_web_cancellation_data(self, data):
        """Valider les données de la requête web"""
        if not isinstance(data, dict):
            return {"success": False, "error": "Format de données invalide"}

        # Vérifier les champs requis
        required_fields = ["ticket_number", "service_id"]
        for field in required_fields:
            if field not in data:
                return {"success": False, "error": f"Champ requis manquant: {field}"}

        # Valider les types
        try:
            data["ticket_number"] = int(data["ticket_number"])
            data["service_id"] = int(data["service_id"])
        except (ValueError, TypeError):
            return {"success": False, "error": "Types de données invalides"}

        # Valider les valeurs
        if data["ticket_number"] <= 0 or data["service_id"] <= 0:
            return {"success": False, "error": "Valeurs invalides"}

        return {"success": True}

    @api.model
    def _find_ticket_for_cancellation(self, ticket_number, service_id):
        """Trouver le ticket avec critères stricts"""
        return self.search(
            [
                ("ticket_number", "=", ticket_number),
                ("service_id", "=", service_id),
                ("state", "in", ["waiting", "called"]),
                ("cancellation_lock", "=", False),
            ],
            limit=1,
        )

    @api.model
    def _check_web_cancellation_security(self, ticket, data):
        """Vérifications de sécurité pour l'annulation web"""
        try:
            # Protection contre les attaques par déni de service
            client_ip = self.env.context.get("client_ip")
            if client_ip:
                recent_cancellations = self.search_count(
                    [
                        (
                            "cancelled_time",
                            ">=",
                            fields.Datetime.now() - timedelta(minutes=10),
                        ),
                        ("cancellation_type", "=", "client"),
                    ]
                )
                if recent_cancellations > 5:  # Max 5 annulations par 10 min
                    return {
                        "success": False,
                        "error": "Trop d'annulations récentes. Veuillez patienter.",
                    }

            # Vérification du token client (optionnel)
            if "client_token" in data:
                expected_token = self._generate_client_token(ticket)
                if data["client_token"] != expected_token:
                    return {"success": False, "error": "Token de sécurité invalide"}

            return {"success": True}

        except Exception as e:
            _logger.error(f"Erreur vérification sécurité: {e}")
            return {"success": False, "error": "Erreur de vérification"}

    def _generate_client_token(self, ticket):
        """Générer un token simple pour la sécurité client (optionnel)"""
        import hashlib

        data = f"{ticket.id}_{ticket.ticket_number}_{ticket.created_time}"
        return hashlib.md5(data.encode()).hexdigest()[:8]

    # Méthodes utilitaires pour le monitoring
    @api.model
    def get_cancellation_statistics(self, date_from=None, date_to=None):
        """Obtenir les statistiques d'annulation"""
        domain = [("state", "=", "cancelled")]

        if date_from:
            domain.append(("cancelled_time", ">=", date_from))
        if date_to:
            domain.append(("cancelled_time", "<=", date_to))

        cancelled_tickets = self.search(domain)

        stats = {
            "total_cancelled": len(cancelled_tickets),
            "by_type": {},
            "by_reason": {},
            "by_service": {},
        }

        # Grouper par type
        for ticket in cancelled_tickets:
            cancel_type = ticket.cancellation_type or "unknown"
            stats["by_type"][cancel_type] = stats["by_type"].get(cancel_type, 0) + 1

            # Par service
            service_name = ticket.service_id.name
            stats["by_service"][service_name] = (
                stats["by_service"].get(service_name, 0) + 1
            )

        return stats

    # Nettoyage automatique des anciens tickets
    @api.model
    def cleanup_old_cancelled_tickets(self, days_to_keep=30):
        """Nettoyer les anciens tickets annulés"""
        cutoff_date = fields.Datetime.now() - timedelta(days=days_to_keep)

        old_tickets = self.search(
            [("state", "=", "cancelled"), ("cancelled_time", "<", cutoff_date)]
        )

        count = len(old_tickets)
        if count > 0:
            old_tickets.unlink()
            _logger.info(f"Nettoyage: {count} anciens tickets annulés supprimés")

        return count

    @api.depends("service_id", "ticket_number")
    def _compute_display_name(self):
        for ticket in self:
            if ticket.service_id and ticket.ticket_number:
                ticket.display_name = (
                    f"{ticket.service_id.name} - #{ticket.ticket_number:03d}"
                )
            else:
                ticket.display_name = "Nouveau Ticket"

    # @api.depends('service_id', 'ticket_number')
    # def _compute_qr_code(self):
    #     """Générer un code QR pour le suivi du ticket"""
    #     base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
    #     for ticket in self:
    #         if ticket.service_id and ticket.ticket_number:
    #             url = f"{base_url}/queue/my_ticket/{ticket.ticket_number}/{ticket.service_id.id}"
    #             ticket.qr_code = url
    #         else:
    #             ticket.qr_code = False

    # 3. CORRECTION de la méthode _compute_waiting_time dans queue_ticket.py
    @api.depends("created_time", "called_time", "state")
    def _compute_waiting_time(self):
        """Calcul CORRIGÉ du temps d'attente"""
        current_time = fields.Datetime.now()

        for ticket in self:
            try:
                if not ticket.created_time:
                    ticket.waiting_time = 0.0
                    continue

                if ticket.state in ["served", "cancelled", "no_show"]:
                    # Ticket terminé
                    if ticket.called_time:
                        # Temps entre création et appel
                        delta = ticket.called_time - ticket.created_time
                        ticket.waiting_time = max(0, delta.total_seconds() / 60.0)
                    elif ticket.state == "served" and ticket.served_time:
                        # Si pas d'heure d'appel mais servi, utiliser l'heure de service
                        delta = ticket.served_time - ticket.created_time
                        ticket.waiting_time = max(0, delta.total_seconds() / 60.0)
                    else:
                        ticket.waiting_time = 0.0

                elif ticket.state == "waiting":
                    # Ticket encore en attente - temps écoulé depuis création
                    delta = current_time - ticket.created_time
                    ticket.waiting_time = max(0, delta.total_seconds() / 60.0)

                else:  # called, serving
                    # Ticket appelé ou en service
                    if ticket.called_time:
                        delta = ticket.called_time - ticket.created_time
                        ticket.waiting_time = max(0, delta.total_seconds() / 60.0)
                    else:
                        # Fallback si pas d'heure d'appel
                        delta = current_time - ticket.created_time
                        ticket.waiting_time = max(0, delta.total_seconds() / 60.0)

            except Exception as e:
                _logger.warning(f"Erreur calcul temps attente ticket {ticket.id}: {e}")
                ticket.waiting_time = 0.0

    @api.depends("served_time", "completed_time", "state")
    def _compute_service_time(self):
        """Calcul optimisé du temps de service"""
        current_time = fields.Datetime.now()

        for ticket in self:
            if ticket.served_time:
                if ticket.completed_time:
                    # Service terminé
                    delta = ticket.completed_time - ticket.served_time
                    ticket.service_time = delta.total_seconds() / 60
                elif ticket.state == "serving":
                    # Service en cours
                    delta = current_time - ticket.served_time
                    ticket.service_time = delta.total_seconds() / 60
                else:
                    ticket.service_time = 0.0
            else:
                ticket.service_time = 0.0

    @api.depends("service_id", "state", "ticket_number", "priority")
    def _compute_estimated_wait(self):
        """Calcul optimisé du temps d'attente estimé"""

        # Grouper les tickets par service pour optimiser
        tickets_by_service = {}
        for ticket in self:
            service_id = ticket.service_id.id
            if service_id not in tickets_by_service:
                tickets_by_service[service_id] = []
            tickets_by_service[service_id].append(ticket)

        for service_id, tickets in tickets_by_service.items():
            service = self.env["queue.service"].browse(service_id)
            if not service.exists():
                continue

            # Récupérer tous les tickets en attente pour ce service
            # CORRECTION: Utilisation de la syntaxe correcte pour le tri
            waiting_tickets = service.waiting_ticket_ids.sorted(
                lambda t: (-self._get_priority_order(t.priority), t.ticket_number)
            )

            for ticket in tickets:
                if ticket.state == "waiting" and ticket in waiting_tickets:
                    # Compter les tickets avant celui-ci (en tenant compte de la priorité)
                    tickets_before = waiting_tickets.filtered(
                        lambda t: (
                            t.priority == "urgent" and ticket.priority != "urgent"
                        )
                        or (t.priority == "high" and ticket.priority == "normal")
                        or (
                            t.priority == ticket.priority
                            and t.ticket_number < ticket.ticket_number
                        )
                    )

                    estimated_minutes = len(tickets_before) * (
                        service.estimated_service_time or 5
                    )
                    ticket.estimated_wait_time = estimated_minutes
                else:
                    ticket.estimated_wait_time = 0.0

    def _get_priority_order(self, priority):
        """Retourne l'ordre numérique de la priorité pour le tri"""
        priority_map = {"urgent": 3, "high": 2, "normal": 1}
        return priority_map.get(priority, 1)

    def action_call_next(self):
        """Appeler le prochain ticket"""
        self.ensure_one()
        if self.state != "waiting":
            raise UserError("Ce ticket n'est pas en attente")

        self.write({"state": "called", "called_time": fields.Datetime.now()})

        # Mettre à jour le ticket actuel du service
        self.service_id.current_ticket_number = self.ticket_number

        # Envoyer notification si contact disponible
        self._send_notification()

        # Log pour le tracking
        self.message_post(body=f"Ticket #{self.ticket_number} appelé")
        return True

    def action_start_service(self):
        """Commencer le service"""
        self.ensure_one()
        if self.state != "called":
            raise UserError("Ce ticket n'a pas été appelé")

        self.write({"state": "serving", "served_time": fields.Datetime.now()})

        self.message_post(body=f"Service du ticket #{self.ticket_number} commencé")
        return True

    def action_complete_service(self):
        """Terminer le service"""
        self.ensure_one()
        if self.state not in ["called", "serving"]:
            raise UserError("Ce ticket n'est pas en cours de service")

        self.write({"state": "served", "completed_time": fields.Datetime.now()})

        # Demander un feedback si email disponible
        if self.customer_email:
            self.action_request_feedback()

        self.message_post(body=f"Service du ticket #{self.ticket_number} terminé")
        return True

    def action_cancel(self):
        """Annuler le ticket"""
        self.ensure_one()
        if self.state in ["served", "cancelled"]:
            raise UserError("Ce ticket ne peut plus être annulé")

        cancel_reason = "Ticket annulé par l'utilisateur"
        self.action_cancel_ticket(reason=cancel_reason)
        # self.state = 'cancelled'
        # self.message_post(body=f"Ticket #{self.ticket_number} annulé")
        return True

    def action_no_show(self):
        """Marquer comme absent"""
        self.ensure_one()
        if self.state != "called":
            raise UserError("Ce ticket n'a pas été appelé")

        self.state = "no_show"
        self.message_post(body=f"Ticket #{self.ticket_number} marqué comme absent")
        return True

    def _send_notification(self):
        """Envoyer notification au client"""
        try:
            if self.customer_email:
                # Utiliser le template d'email si disponible
                template = self.env.ref(
                    "queue_management.email_ticket_called", raise_if_not_found=False
                )
                if template:
                    template.send_mail(self.id, force_send=True)
                else:
                    # Créer un email simple
                    mail_values = {
                        "subject": f"Votre ticket #{self.ticket_number} est appelé",
                        "body_html": f"""
                            <p>Bonjour,</p>
                            <p>Votre ticket <strong>#{self.ticket_number}</strong> pour le service 
                            <strong>{self.service_id.name}</strong> est maintenant appelé.</p>
                            <p>Veuillez vous présenter au guichet.</p>
                        """,
                        "email_to": self.customer_email,
                        "auto_delete": True,
                    }
                    self.env["mail.mail"].sudo().create(mail_values).send()

                self.notification_sent = True

            # TODO: Intégrer SMS si nécessaire
            if self.customer_phone:
                self._send_sms_notification(
                    f"Votre ticket #{self.ticket_number} est appelé pour {self.service_id.name}"
                )

        except Exception as e:
            _logger.error(f"Erreur envoi notification: {e}")

    def _send_sms_notification(self, message):
        """Envoyer notification SMS (à personnaliser selon votre provider SMS)"""
        if not self.customer_phone:
            return False

        try:
            # TODO: Intégrer votre service SMS préféré
            # Exemple avec un service générique:
            _logger.info(f"SMS à envoyer à {self.customer_phone}: {message}")
            return True
        except Exception as e:
            _logger.error(f"Erreur envoi SMS: {e}")
            return False

    def action_request_feedback(self):
        """Demander un feedback après service"""
        if self.state != "served":
            return False

        try:
            template = self.env.ref(
                "queue_management.email_feedback_request", raise_if_not_found=False
            )
            if template and self.customer_email:
                template.send_mail(self.id, force_send=True)
            else:
                # Email simple de demande de feedback
                mail_values = {
                    "subject": f"Évaluez votre expérience - Service {self.service_id.name}",
                    "body_html": f"""
                        <p>Bonjour,</p>
                        <p>Nous espérons que votre passage pour le service <strong>{self.service_id.name}</strong> 
                        s'est bien déroulé.</p>
                        <p>Nous aimerions connaître votre avis pour améliorer nos services.</p>
                        <p>Ticket: <strong>#{self.ticket_number}</strong></p>
                    """,
                    "email_to": self.customer_email,
                    "auto_delete": True,
                }
                self.env["mail.mail"].sudo().create(mail_values).send()
            return True
        except Exception as e:
            _logger.error(f"Erreur demande feedback: {e}")
            return False

    def submit_feedback(self, rating, feedback=""):
        """Soumettre un feedback"""
        self.write({"rating": rating, "feedback": feedback})
        self.message_post(body=f"Feedback reçu: {rating}/5 étoiles")
        return True

    @api.model
    def get_my_ticket_status(self, ticket_number, service_id):
        """Obtenir le statut d'un ticket spécifique (pour les clients)"""
        ticket = self.search(
            [("ticket_number", "=", ticket_number), ("service_id", "=", service_id)],
            limit=1,
        )

        if not ticket:
            return {"error": "Ticket non trouvé"}

        # Calculer la position
        tickets_before = self.search_count(
            [
                ("service_id", "=", service_id),
                ("state", "=", "waiting"),
                ("ticket_number", "<", ticket_number),
            ]
        )

        return {
            "ticket_number": ticket.ticket_number,
            "state": ticket.state,
            "position": tickets_before + 1 if ticket.state == "waiting" else 0,
            "estimated_wait": ticket.estimated_wait_time,
            "service_name": ticket.service_id.name,
            "current_serving": ticket.service_id.current_ticket_number,
        }

    # Méthode de mise à jour en lot pour les performances
    @api.model
    def bulk_update_statistics(self, service_ids=None):
        """Mise à jour en lot des statistiques pour améliorer les performances"""

        if not service_ids:
            services = self.search([("active", "=", True)])
        else:
            services = self.browse(service_ids)

        if not services:
            return {"updated_services": 0}

        # Désactiver temporairement le recalcul automatique
        with self.env.norecompute():

            # Mise à jour des compteurs de tickets
            for service in services:
                # Synchroniser le compteur avec le dernier ticket
                max_ticket_number = max(
                    service.ticket_ids.mapped("ticket_number") + [0]
                )
                if service.current_ticket_number != max_ticket_number:
                    service.current_ticket_number = max_ticket_number

            # Recalculer tous les champs dépendants
            services.modified(["ticket_ids"])

        # Forcer le recalcul des champs computed
        services.recompute()

        return {"updated_services": len(services), "timestamp": fields.Datetime.now()}

    # Action programmée pour maintenir la cohérence des données
    @api.model
    def scheduled_data_maintenance(self):
        """Maintenance programmée des données (à appeler via cron)"""

        _logger.info("Début de la maintenance programmée des données")

        # 1. Validation de l'intégrité
        integrity_report = self.validate_data_integrity()

        # 2. Mise à jour des statistiques
        update_report = self.bulk_update_statistics()

        # 3. Nettoyage des anciennes données (garder 30 jours)
        cleanup_report = self.cleanup_old_data(days_to_keep=30)

        # 4. Vider le cache
        self.clear_stats_cache()

        # 5. Log du rapport
        maintenance_report = {
            "timestamp": fields.Datetime.now(),
            "integrity_issues_fixed": integrity_report.get("fixes_applied", 0),
            "services_updated": update_report.get("updated_services", 0),
            "old_tickets_cleaned": cleanup_report.get("tickets_count", 0),
        }

        _logger.info(f"Maintenance terminée: {maintenance_report}")

        return maintenance_report

    @api.model
    def cancel_ticket_web(self, data):
        """
        Méthode pour annuler un ticket via l'interface web

        Args:
            data (dict): Dictionnaire contenant:
                - ticket_number (int): Numéro du ticket
                - service_id (int): ID du service
                - reason (str, optionnel): Raison de l'annulation

        Returns:
            dict: Réponse avec succès/erreur
        """
        try:
            # Validation des données d'entrée
            ticket_number = data.get("ticket_number")
            service_id = data.get("service_id")
            reason = data.get("reason", "")

            # Vérifications de base
            if not ticket_number:
                return {"success": False, "error": "Numéro de ticket manquant"}

            if not service_id:
                return {"success": False, "error": "Service non spécifié"}

            # Rechercher le ticket
            ticket = self.search(
                [
                    ("ticket_number", "=", ticket_number),
                    ("service_id", "=", service_id),
                ],
                limit=1,
            )

            if not ticket:
                return {
                    "success": False,
                    "error": f"Ticket #{ticket_number} non trouvé pour ce service",
                }

            # Vérifier l'état du ticket
            if ticket.state not in ["waiting", "called"]:
                state_names = {
                    "waiting": "En Attente",
                    "called": "Appelé",
                    "serving": "En Service",
                    "served": "Terminé",
                    "cancelled": "Annulé",
                    "no_show": "Absent",
                }
                current_state = state_names.get(ticket.state, ticket.state)

                return {
                    "success": False,
                    "error": f"Impossible d'annuler un ticket {current_state.lower()}",
                }

            # Préparer la raison d'annulation
            cancel_reason = "Annulation client via web"
            if reason and reason.strip():
                cancel_reason = f"Annulation client: {reason.strip()}"

            # Effectuer l'annulation
            try:
                ticket.action_cancel_ticket(reason=cancel_reason)

                # Log pour traçabilité
                _logger.info(
                    f"Ticket #{ticket_number} (ID: {ticket.id}) annulé via web - Service: {ticket.service_id.name}"
                )

                return {
                    "success": True,
                    "message": f"Ticket #{ticket_number} annulé avec succès",
                    "ticket_id": ticket.id,
                    "new_state": "cancelled",
                }

            except UserError as ue:
                _logger.warning(
                    f"Erreur UserError lors de l'annulation du ticket #{ticket_number}: {ue}"
                )
                return {"success": False, "error": str(ue)}
            except Exception as e:
                _logger.error(
                    f"Erreur lors de l'annulation du ticket #{ticket_number}: {e}"
                )
                return {
                    "success": False,
                    "error": "Erreur lors de l'annulation. Veuillez réessayer.",
                }

        except Exception as e:
            _logger.error(f"Erreur dans cancel_ticket_web: {e}")
            return {"success": False, "error": "Erreur système. Veuillez réessayer."}

    @api.model
    def get_ticket_status_web(self, ticket_number, service_id):
        """
        Méthode complémentaire pour obtenir le statut d'un ticket via web
        (Amélioration de get_my_ticket_status pour l'interface web)

        Args:
            ticket_number (int): Numéro du ticket
            service_id (int): ID du service

        Returns:
            dict: Statut du ticket ou erreur
        """
        try:
            ticket = self.search(
                [
                    ("ticket_number", "=", ticket_number),
                    ("service_id", "=", service_id),
                ],
                limit=1,
            )

            if not ticket:
                return {"success": False, "error": "Ticket non trouvé"}

            # Calculer la position dans la file
            position = 0
            if ticket.state == "waiting":
                # Compter les tickets avant celui-ci (avec priorité)
                tickets_before = self.search(
                    [
                        ("service_id", "=", service_id),
                        ("state", "=", "waiting"),
                        "|",
                        ("priority", "in", ["urgent", "high"]),
                        "&",
                        ("priority", "=", ticket.priority),
                        ("ticket_number", "<", ticket_number),
                    ]
                )
                position = len(tickets_before) + 1

            # Statut détaillé
            state_labels = {
                "waiting": "En Attente",
                "called": "Appelé",
                "serving": "En Service",
                "served": "Terminé",
                "cancelled": "Annulé",
                "no_show": "Absent",
            }

            return {
                "success": True,
                "ticket_number": ticket.ticket_number,
                "state": ticket.state,
                "state_label": state_labels.get(ticket.state, ticket.state),
                "position": position,
                "estimated_wait_time": ticket.estimated_wait_time,
                "service_name": ticket.service_id.name,
                "current_serving": ticket.service_id.current_ticket_number or 0,
                "can_cancel": ticket.state in ["waiting", "called"],
                "created_time": (
                    ticket.created_time.strftime("%d/%m/%Y %H:%M")
                    if ticket.created_time
                    else ""
                ),
                "waiting_time": (
                    round(ticket.waiting_time, 1) if ticket.waiting_time else 0
                ),
            }

        except Exception as e:
            _logger.error(f"Erreur dans get_ticket_status_web: {e}")
            return {
                "success": False,
                "error": "Erreur lors de la récupération du statut",
            }

    def action_cancel_ticket(self, reason=None):
        """
        Version améliorée de action_cancel_ticket avec meilleure gestion d'erreurs
        (Remplace la version existante dans votre code)
        """
        self.ensure_one()

        # Vérifier l'état actuel
        if self.state not in ["waiting", "called"]:
            state_names = {
                "waiting": "En Attente",
                "called": "Appelé",
                "serving": "En Service",
                "served": "Terminé",
                "cancelled": "Annulé",
                "no_show": "Absent",
            }
            current_state = state_names.get(self.state, self.state)
            raise UserError(f"Ce ticket ({current_state}) ne peut plus être annulé")

        # Préparer la raison
        if not reason:
            cancel_reason = "Ticket annulé"
        else:
            cancel_reason = reason.strip()

        # Effectuer l'annulation avec transaction
        try:
            values_to_write = {
                "state": "cancelled",
                "completed_time": fields.Datetime.now(),
            }

            # Ajouter la raison aux notes
            existing_notes = self.notes or ""
            timestamp = fields.Datetime.now().strftime("%d/%m/%Y %H:%M")
            new_note = f"[{timestamp}] {cancel_reason}"

            if existing_notes:
                values_to_write["notes"] = f"{existing_notes}\n{new_note}"
            else:
                values_to_write["notes"] = new_note

            self.write(values_to_write)

            # Message de suivi
            self.message_post(
                body=f"Ticket #{self.ticket_number} annulé",
                subject=f"Annulation ticket #{self.ticket_number}",
            )

            # Notification (non bloquante)
            try:
                self._notify_ticket_cancelled(cancel_reason)
            except Exception as e:
                _logger.warning(
                    f"Erreur notification annulation ticket #{self.ticket_number}: {e}"
                )

            return True

        except Exception as e:
            _logger.error(f"Erreur annulation ticket #{self.ticket_number}: {e}")
            raise UserError(f"Erreur lors de l'annulation: {str(e)}")

    def _notify_ticket_cancelled(self, reason=""):
        """Notification lors de l'annulation - AMÉLIORÉE"""
        try:
            if self.customer_email:
                # Créer un email de notification d'annulation
                mail_values = {
                    "subject": f"Ticket #{self.ticket_number} annulé - {self.service_id.name}",
                    "body_html": f"""
                        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                            <h2 style="color: #dc3545;">Ticket Annulé</h2>
                            <p>Bonjour,</p>
                            <p>Votre ticket <strong>#{self.ticket_number}</strong> pour le service 
                            <strong>{self.service_id.name}</strong> a été annulé.</p>
                            {f"<p><strong>Raison:</strong> {reason}</p>" if reason else ""}
                            <p>Si vous souhaitez reprendre un nouveau ticket, vous pouvez retourner sur notre système.</p>
                            <hr style="border: 1px solid #eee; margin: 20px 0;">
                            <p style="color: #666; font-size: 12px;">
                                Ticket annulé le: {fields.Datetime.now().strftime('%d/%m/%Y à %H:%M')}
                            </p>
                        </div>
                    """,
                    "email_to": self.customer_email,
                    "auto_delete": True,
                }
                self.env["mail.mail"].sudo().create(mail_values).send()
                _logger.info(
                    f"Email d'annulation envoyé à {self.customer_email} pour ticket #{self.ticket_number}"
                )

        except Exception as e:
            _logger.error(f"Erreur envoi notification annulation: {e}")

    # Dans queue_ticket.py
    @api.model
    def get_ticket_numbering_report(self):
        """Rapport sur l'état de la numérotation"""
        services = self.env["queue.service"].search([("active", "=", True)])

        report = []
        for service in services:
            status = service.get_numbering_status()
            report.append(status)

        return report

    # Remplacer la méthode _generate_next_ticket_number
    def _generate_next_ticket_number(self, service):
        """Générer le prochain numéro de ticket pour un service donné - Version améliorée"""
        try:
            # Utiliser la nouvelle méthode du service pour obtenir le numéro
            if hasattr(service, "_get_next_ticket_number"):
                return service._get_next_ticket_number()

            # Fallback: méthode existante
            if hasattr(service, "next_ticket_number") and service.next_ticket_number:
                next_number = service.next_ticket_number
                # Incrémenter pour le prochain
                service.sudo().write({"next_ticket_number": next_number + 1})
                return next_number

            # Méthode de secours: chercher le maximum existant
            last_ticket = self.env["queue.ticket"].search(
                [("service_id", "=", service.id)], order="ticket_number desc", limit=1
            )

            if last_ticket:
                next_number = last_ticket.ticket_number + 1
            else:
                next_number = 1

            # Mettre à jour le compteur du service
            service.sudo().write(
                {
                    "next_ticket_number": next_number + 1,
                    "current_ticket_number": next_number,
                }
            )

            return next_number

        except Exception as e:
            _logger.error(f"Erreur génération numéro ticket: {e}")
            # Fallback: utiliser un timestamp modifié
            import time

            fallback_number = int(time.time()) % 100000
            _logger.warning(f"Utilisation du numéro de fallback: {fallback_number}")
            return fallback_number

    # Nouvelle méthode de validation
    @api.constrains("ticket_number", "service_id")
    def _check_ticket_number_unique(self):
        """Vérifier l'unicité du numéro de ticket par service"""
        for ticket in self:
            if ticket.ticket_number and ticket.service_id:
                existing = self.search(
                    [
                        ("service_id", "=", ticket.service_id.id),
                        ("ticket_number", "=", ticket.ticket_number),
                        ("id", "!=", ticket.id),
                    ]
                )
                if existing:
                    raise ValidationError(
                        _("Le numéro de ticket %s existe déjà pour le service %s")
                        % (ticket.ticket_number, ticket.service_id.name)
                    )

    # Nouvelle méthode pour corriger les incohérences
    @api.model
    def fix_ticket_numbering(self, service_ids=None):
        """Corriger les incohérences dans la numérotation des tickets"""
        domain = []
        if service_ids:
            domain = [("service_id", "in", service_ids)]

        services = self.env["queue.service"].search(domain)

        fixed_count = 0
        for service in services:
            # Trouver tous les tickets du service
            tickets = self.search([("service_id", "=", service.id)])

            if not tickets:
                continue

            # Trouver le numéro maximum
            max_number = max(tickets.mapped("ticket_number"))

            # Synchroniser avec le service
            service.sync_ticket_numbers()

            fixed_count += 1

        _logger.info(f"Numérotation corrigée pour {fixed_count} services")
        return fixed_count
