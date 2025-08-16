# ==============================================================================
# AMÉLIORATION DE LA GESTION D'ANNULATION DES TICKETS
# ==============================================================================

# 1. MODÈLE - Améliorations dans models/queue_ticket.py
# ==============================================================================
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError, AccessError
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

class QueueTicket(models.Model):
    _name = 'queue.ticket'
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = 'Ticket de File d\'Attente'
    _order = 'ticket_number desc'
    _rec_name = 'display_name'

    # Informations de base
    service_id = fields.Many2one('queue.service', 'Service', required=True, ondelete='cascade')
    ticket_number = fields.Integer('Numéro de Ticket', required=True)
    display_name = fields.Char('Nom d\'affichage', compute='_compute_display_name', store=True)
    
    # Informations client
    customer_name = fields.Char('Nom du Client')
    customer_phone = fields.Char('Téléphone')
    customer_email = fields.Char('Email')
    
    # États et timing
    state = fields.Selection([
        ('waiting', 'En Attente'),
        ('called', 'Appelé'),
        ('serving', 'En Service'),
        ('served', 'Servi'),
        ('cancelled', 'Annulé'),
        ('no_show', 'Absent')
    ], string='État', default='waiting', tracking=True)
    
    priority = fields.Selection([
        ('normal', 'Normal'),
        ('high', 'Priorité'),
        ('urgent', 'Urgent')
    ], string='Priorité', default='normal')
    
    # Timestamps
    created_time = fields.Datetime('Heure de Création', default=fields.Datetime.now)
    called_time = fields.Datetime('Heure d\'Appel')
    served_time = fields.Datetime('Heure de Service')
    completed_time = fields.Datetime('Heure de Fin')
    
    # Calculs
    waiting_time = fields.Float('Temps d\'Attente (min)', compute='_compute_waiting_time', store=True)
    service_time = fields.Float('Temps de Service (min)', compute='_compute_service_time', store=True)
    estimated_wait_time = fields.Float('Temps d\'attente estimé', compute='_compute_estimated_wait', store=True )
    
    # Autres
    notes = fields.Text('Notes')
    notification_sent = fields.Boolean('Notification envoyée', default=False)
    qr_code = fields.Char('Code QR', compute='_compute_qr_code', store=True)
    rating = fields.Selection([
        ('1', '⭐'),
        ('2', '⭐⭐'),
        ('3', '⭐⭐⭐'),
        ('4', '⭐⭐⭐⭐'),
        ('5', '⭐⭐⭐⭐⭐')
    ], string='Évaluation')
    feedback = fields.Text('Commentaires')
    # Nouveaux champs pour l'annulation améliorée
    cancellation_reason = fields.Text('Raison d\'annulation', tracking=True)
    cancelled_by = fields.Many2one('res.users', 'Annulé par', tracking=True)
    cancelled_time = fields.Datetime('Heure d\'annulation', tracking=True)
    cancellation_type = fields.Selection([
        ('client', 'Annulation client'),
        ('agent', 'Annulation agent'),
        ('system', 'Annulation système'),
        ('timeout', 'Timeout')
    ], string='Type d\'annulation', tracking=True)
    
    # Système de verrouillage pour éviter les doubles annulations
    cancellation_lock = fields.Boolean('Verrouillage annulation', default=False)
    
    # Historique des actions sur le ticket
    action_history = fields.Text('Historique des actions', default='')

    @api.model
    def auto_cancel_timeout_tickets(self, timeout_minutes=15):
        timeout_date = datetime.now() - timedelta(minutes=timeout_minutes)
        timeout_tickets = self.search([
            ('state', '=', 'called'),
            ('called_time', '<', timeout_date)
        ])
        for ticket in timeout_tickets:
            try:
                ticket.action_cancel_ticket_v2(
                    reason=f'Timeout automatique après {timeout_minutes} minutes sans réponse',
                    cancellation_type='timeout'
                )
                _logger.info(f'Ticket #{ticket.ticket_number} annulé par timeout')
            except Exception as e:
                _logger.error(f'Erreur timeout ticket #{ticket.ticket_number}: {e}')

    @api.model
    def scheduled_cleanup_and_maintenance(self):
        cleanup_result = self.cleanup_old_cancelled_tickets(days_to_keep=30)
        _logger.info(f'Nettoyage effectué: {cleanup_result} tickets supprimés')

        maintenance_result = self.scheduled_data_maintenance()
        _logger.info(f'Maintenance des données: {maintenance_result}')

    @api.model
    def scheduled_update_estimated_times(self):
        waiting_tickets = self.search([('state', '=', 'waiting')])
        if waiting_tickets:
            waiting_tickets._compute_estimated_wait()
            _logger.info(f"Temps d'attente mis à jour pour {len(waiting_tickets)} tickets")

    priority_badge = fields.Html(compute='_compute_priority_badge', sanitize=False)

    @api.depends('priority')
    def _compute_priority_badge(self):
        for rec in self:
            if rec.priority == 'urgent':
                badge = '<span class="badge badge-danger">URGENT</span>'
            elif rec.priority == 'high':
                badge = '<span class="badge badge-warning">PRIORITÉ</span>'
            else:
                badge = '<span class="badge badge-secondary">NORMAL</span>'
            rec.priority_badge = badge

    # @api.model
    # def create(self, vals):
    #     """Override create avec historique initial"""
    #     ticket = super().create(vals)
    #     ticket._add_action_history('created', 'Ticket créé')
    #     return ticket

    @api.model
    def create(self, vals):
        """Override create pour générer automatiquement le ticket_number"""
        # Si ticket_number n'est pas fourni, le générer automatiquement
        if 'ticket_number' not in vals or not vals.get('ticket_number'):
            service_id = vals.get('service_id')
            if not service_id:
                raise ValidationError("Service requis pour créer un ticket")
            
            service = self.env['queue.service'].browse(service_id)
            if not service.exists():
                raise ValidationError("Service non trouvé")
            
            # Générer le numéro de ticket
            vals['ticket_number'] = self._generate_next_ticket_number(service)
            _logger.info(f"Ticket number auto-généré: {vals['ticket_number']} pour service {service.name}")
        
        # S'assurer que created_time est défini
        if 'created_time' not in vals:
            vals['created_time'] = fields.Datetime.now()
        
        # Créer le ticket
        ticket = super(QueueTicket, self).create(vals)
        
        # Ajouter une entrée dans l'historique
        ticket._add_action_history('created', f"Ticket #{ticket.ticket_number} créé")
        
        # Calculer le temps d'attente estimé après création
        ticket._compute_estimated_wait()
        
        return ticket

    def get_queue_position(self):
        all_waiting = self.env['queue.ticket'].sudo().search([
            ('service_id', '=', self.service_id.id),
            ('state', '=', 'waiting')
        ], order='create_date asc')

        for index, t in enumerate(all_waiting):
            if t.id == self.id:
                return index + 1
        return 0


    def _generate_next_ticket_number(self, service):
        """Générer le prochain numéro de ticket pour un service donné"""
        try:
            # Méthode 1: Utiliser next_ticket_number du service
            if hasattr(service, 'next_ticket_number') and service.next_ticket_number:
                next_number = service.next_ticket_number
                # Incrémenter pour le prochain
                service.sudo().write({'next_ticket_number': next_number + 1})
                return next_number
            
            # Mettre à jour le compteur du service
            service.sudo().write({'next_ticket_number': next_number + 1})
            
            return next_number
            
        except Exception as e:
            _logger.error(f"Erreur génération numéro ticket: {e}")
            # Fallback: utiliser un timestamp modifié
            import time
            fallback_number = int(time.time()) % 100000
            _logger.warning(f"Utilisation du numéro de fallback: {fallback_number}")
            return fallback_number

    def _add_action_history(self, action_type, description, user_id=None):
        """Ajouter une action à l'historique"""
        if not user_id:
            user_id = self.env.user.id
        
        timestamp = fields.Datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        user_name = self.env['res.users'].browse(user_id).name
        
        new_entry = f"[{timestamp}] {action_type.upper()}: {description} (par {user_name})"
        
        if self.action_history:
            self.action_history = f"{self.action_history}\n{new_entry}"
        else:
            self.action_history = new_entry

    def action_cancel_ticket_v2(self, reason=None, cancellation_type='client', force=False):
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
            if not validation_result['success']:
                return validation_result
            
            # 2. Acquisition du verrou
            lock_result = self._acquire_cancellation_lock()
            if not lock_result['success']:
                return lock_result
            
            try:
                # 3. Effectuer l'annulation
                cancel_result = self._execute_cancellation(reason, cancellation_type)
                if not cancel_result['success']:
                    return cancel_result
                
                # 4. Actions post-annulation
                self._post_cancellation_actions(reason, cancellation_type)
                
                return {
                    'success': True,
                    'message': f'Ticket #{self.ticket_number} annulé avec succès',
                    'ticket_id': self.id,
                    'new_state': 'cancelled'
                }
                
            finally:
                # 5. Libérer le verrou (dans tous les cas)
                self._release_cancellation_lock()
                
        except Exception as e:
            _logger.error(f"Erreur critique annulation ticket #{self.ticket_number}: {e}")
            return {
                'success': False,
                'error': 'Erreur système lors de l\'annulation'
            }

    def _validate_cancellation(self, force=False):
        """Valider si le ticket peut être annulé"""
        try:
            # Vérifier l'état du ticket
            if self.state not in ['waiting', 'called']:
                state_labels = {
                    'serving': 'en cours de service',
                    'served': 'déjà terminé',
                    'cancelled': 'déjà annulé',
                    'no_show': 'marqué comme absent'
                }
                current_state = state_labels.get(self.state, self.state)
                return {
                    'success': False,
                    'error': f'Impossible d\'annuler un ticket {current_state}'
                }
            
            # Vérifier le verrouillage (sauf si force=True)
            if not force and self.cancellation_lock:
                return {
                    'success': False,
                    'error': 'Ticket en cours d\'annulation par un autre processus'
                }
            
            # Vérifications métier supplémentaires
            config = self.env['ir.config_parameter'].sudo()
            
            # Délai maximum pour annulation client
            if hasattr(self, 'cancellation_type') and self.cancellation_type == 'client':
                max_delay = int(config.get_param('queue.max_cancellation_delay_minutes', 30))
                if self.created_time:
                    time_elapsed = (fields.Datetime.now() - self.created_time).total_seconds() / 60
                    if time_elapsed > max_delay:
                        return {
                            'success': False,
                            'error': f'Délai d\'annulation dépassé ({max_delay} minutes max)'
                        }
            
            # Vérifier si les annulations sont autorisées
            allow_cancellation = config.get_param('queue.allow_ticket_cancellation', 'True').lower() == 'true'
            if not allow_cancellation and not force:
                return {
                    'success': False,
                    'error': 'Les annulations de tickets sont temporairement désactivées'
                }
            
            return {'success': True}
            
        except Exception as e:
            _logger.error(f"Erreur validation annulation: {e}")
            return {
                'success': False,
                'error': 'Erreur lors de la validation'
            }

    def _acquire_cancellation_lock(self):
        """Acquérir le verrou d'annulation"""
        try:
            # Vérifier si déjà verrouillé
            self.env.cr.execute(
                "SELECT cancellation_lock FROM queue_ticket WHERE id = %s FOR UPDATE NOWAIT",
                (self.id,)
            )
            result = self.env.cr.fetchone()
            
            if result and result[0]:
                return {
                    'success': False,
                    'error': 'Ticket en cours de traitement par un autre utilisateur'
                }
            
            # Acquérir le verrou
            self.env.cr.execute(
                "UPDATE queue_ticket SET cancellation_lock = true WHERE id = %s",
                (self.id,)
            )
            
            return {'success': True}
            
        except Exception as e:
            _logger.error(f"Erreur acquisition verrou: {e}")
            return {
                'success': False,
                'error': 'Impossible de verrouiller le ticket'
            }

    def _execute_cancellation(self, reason, cancellation_type):
        """Exécuter l'annulation proprement dite"""
        try:
            # Préparer les valeurs
            cancellation_data = {
                'state': 'cancelled',
                'cancelled_time': fields.Datetime.now(),
                'cancelled_by': self.env.user.id,
                'cancellation_type': cancellation_type,
                'cancellation_reason': reason or 'Aucune raison spécifiée'
            }
            
            # Mettre à jour avec validation
            self.with_context(skip_validation=True).write(cancellation_data)
            
            # Ajouter à l'historique
            self._add_action_history(
                'cancelled',
                f'Ticket annulé - Type: {cancellation_type} - Raison: {reason}'
            )
            
            # Commit de la transaction pour sécuriser
            self.env.cr.commit()
            
            return {'success': True}
            
        except Exception as e:
            # Rollback en cas d'erreur
            self.env.cr.rollback()
            _logger.error(f"Erreur exécution annulation: {e}")
            return {
                'success': False,
                'error': 'Erreur lors de l\'enregistrement de l\'annulation'
            }

    def _release_cancellation_lock(self):
        """Libérer le verrou d'annulation"""
        try:
            self.env.cr.execute(
                "UPDATE queue_ticket SET cancellation_lock = false WHERE id = %s",
                (self.id,)
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
                message_type='notification'
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
            if cancellation_type == 'client':
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
                'subject': subject,
                'body_html': message,
                'email_to': self.customer_email,
                'auto_delete': True,
                'email_from': self.env.company.email or 'noreply@example.com'
            }
            
            self.env['mail.mail'].sudo().create(mail_values).send()
            
        except Exception as e:
            _logger.error(f"Erreur notification annulation: {e}")

    @api.model
    def cancel_ticket_web_v2(self, data):
        """
        Version améliorée de cancel_ticket_web avec validation renforcée
        
        Args:
            data (dict): {
                'ticket_number': int,
                'service_id': int, 
                'reason': str (optionnel),
                'client_token': str (optionnel, pour sécurité)
            }
        
        Returns:
            dict: Résultat de l'opération
        """
        try:
            # 1. Validation des données d'entrée
            validation_result = self._validate_web_cancellation_data(data)
            if not validation_result['success']:
                return validation_result
            
            ticket_number = data['ticket_number']
            service_id = data['service_id']
            reason = data.get('reason', '').strip()
            
            # 2. Rechercher le ticket avec vérifications de sécurité
            ticket = self._find_ticket_for_cancellation(ticket_number, service_id)
            if not ticket:
                return {
                    'success': False,
                    'error': 'Ticket non trouvé ou non éligible à l\'annulation'
                }
            
            # 3. Vérifications de sécurité supplémentaires
            security_check = self._check_web_cancellation_security(ticket, data)
            if not security_check['success']:
                return security_check
            
            # 4. Effectuer l'annulation
            cancel_result = ticket.action_cancel_ticket_v2(
                reason=reason or 'Annulation via interface web',
                cancellation_type='client'
            )
            
            return cancel_result
            
        except Exception as e:
            _logger.error(f"Erreur dans cancel_ticket_web_v2: {e}")
            return {
                'success': False,
                'error': 'Erreur système lors de l\'annulation'
            }

    @api.model
    def _validate_web_cancellation_data(self, data):
        """Valider les données de la requête web"""
        if not isinstance(data, dict):
            return {'success': False, 'error': 'Format de données invalide'}
        
        # Vérifier les champs requis
        required_fields = ['ticket_number', 'service_id']
        for field in required_fields:
            if field not in data:
                return {'success': False, 'error': f'Champ requis manquant: {field}'}
        
        # Valider les types
        try:
            data['ticket_number'] = int(data['ticket_number'])
            data['service_id'] = int(data['service_id'])
        except (ValueError, TypeError):
            return {'success': False, 'error': 'Types de données invalides'}
        
        # Valider les valeurs
        if data['ticket_number'] <= 0 or data['service_id'] <= 0:
            return {'success': False, 'error': 'Valeurs invalides'}
        
        return {'success': True}

    @api.model
    def _find_ticket_for_cancellation(self, ticket_number, service_id):
        """Trouver le ticket avec critères stricts"""
        return self.search([
            ('ticket_number', '=', ticket_number),
            ('service_id', '=', service_id),
            ('state', 'in', ['waiting', 'called']),
            ('cancellation_lock', '=', False)
        ], limit=1)

    @api.model
    def _check_web_cancellation_security(self, ticket, data):
        """Vérifications de sécurité pour l'annulation web"""
        try:
            # Protection contre les attaques par déni de service
            client_ip = self.env.context.get('client_ip')
            if client_ip:
                recent_cancellations = self.search_count([
                    ('cancelled_time', '>=', fields.Datetime.now() - timedelta(minutes=10)),
                    ('cancellation_type', '=', 'client')
                ])
                if recent_cancellations > 5:  # Max 5 annulations par 10 min
                    return {
                        'success': False,
                        'error': 'Trop d\'annulations récentes. Veuillez patienter.'
                    }
            
            # Vérification du token client (optionnel)
            if 'client_token' in data:
                expected_token = self._generate_client_token(ticket)
                if data['client_token'] != expected_token:
                    return {
                        'success': False,
                        'error': 'Token de sécurité invalide'
                    }
            
            return {'success': True}
            
        except Exception as e:
            _logger.error(f"Erreur vérification sécurité: {e}")
            return {
                'success': False,
                'error': 'Erreur de vérification'
            }

    def _generate_client_token(self, ticket):
        """Générer un token simple pour la sécurité client (optionnel)"""
        import hashlib
        data = f"{ticket.id}_{ticket.ticket_number}_{ticket.created_time}"
        return hashlib.md5(data.encode()).hexdigest()[:8]

    # Méthodes utilitaires pour le monitoring
    @api.model
    def get_cancellation_statistics(self, date_from=None, date_to=None):
        """Obtenir les statistiques d'annulation"""
        domain = [('state', '=', 'cancelled')]
        
        if date_from:
            domain.append(('cancelled_time', '>=', date_from))
        if date_to:
            domain.append(('cancelled_time', '<=', date_to))
        
        cancelled_tickets = self.search(domain)
        
        stats = {
            'total_cancelled': len(cancelled_tickets),
            'by_type': {},
            'by_reason': {},
            'by_service': {}
        }
        
        # Grouper par type
        for ticket in cancelled_tickets:
            cancel_type = ticket.cancellation_type or 'unknown'
            stats['by_type'][cancel_type] = stats['by_type'].get(cancel_type, 0) + 1
            
            # Par service
            service_name = ticket.service_id.name
            stats['by_service'][service_name] = stats['by_service'].get(service_name, 0) + 1
        
        return stats

    # Nettoyage automatique des anciens tickets
    @api.model
    def cleanup_old_cancelled_tickets(self, days_to_keep=30):
        """Nettoyer les anciens tickets annulés"""
        cutoff_date = fields.Datetime.now() - timedelta(days=days_to_keep)
        
        old_tickets = self.search([
            ('state', '=', 'cancelled'),
            ('cancelled_time', '<', cutoff_date)
        ])
        
        count = len(old_tickets)
        if count > 0:
            old_tickets.unlink()
            _logger.info(f"Nettoyage: {count} anciens tickets annulés supprimés")
        
        return count

    # @api.model
    # def create(self, vals):
    #     """Override create pour générer automatiquement le numéro de ticket"""
    #     if 'ticket_number' not in vals and 'service_id' in vals:
    #         service = self.env['queue.service'].browse(vals['service_id'])
    #         if service.exists():
    #             vals['ticket_number'] = service.next_ticket_number
    #             # Incrémenter le compteur du service
    #             service.next_ticket_number += 1
    #     return super(QueueTicket, self).create(vals)
    
    @api.depends('service_id', 'ticket_number')
    def _compute_display_name(self):
        for ticket in self:
            if ticket.service_id and ticket.ticket_number:
                ticket.display_name = f"{ticket.service_id.name} - #{ticket.ticket_number:03d}"
            else:
                ticket.display_name = "Nouveau Ticket"

    @api.depends('service_id', 'ticket_number')
    def _compute_qr_code(self):
        """Générer un code QR pour le suivi du ticket"""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for ticket in self:
            if ticket.service_id and ticket.ticket_number:
                url = f"{base_url}/queue/my_ticket/{ticket.ticket_number}/{ticket.service_id.id}"
                ticket.qr_code = url
            else:
                ticket.qr_code = False

    # 3. CORRECTION de la méthode _compute_waiting_time dans queue_ticket.py
    @api.depends('created_time', 'called_time', 'state')
    def _compute_waiting_time(self):
        """Calcul CORRIGÉ du temps d'attente"""
        current_time = fields.Datetime.now()
        
        for ticket in self:
            try:
                if not ticket.created_time:
                    ticket.waiting_time = 0.0
                    continue
                    
                if ticket.state in ['served', 'cancelled', 'no_show']:
                    # Ticket terminé
                    if ticket.called_time:
                        # Temps entre création et appel
                        delta = ticket.called_time - ticket.created_time
                        ticket.waiting_time = max(0, delta.total_seconds() / 60.0)
                    elif ticket.state == 'served' and ticket.served_time:
                        # Si pas d'heure d'appel mais servi, utiliser l'heure de service
                        delta = ticket.served_time - ticket.created_time
                        ticket.waiting_time = max(0, delta.total_seconds() / 60.0)
                    else:
                        ticket.waiting_time = 0.0
                        
                elif ticket.state == 'waiting':
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

    @api.depends('served_time', 'completed_time', 'state')
    def _compute_service_time(self):
        """Calcul optimisé du temps de service"""
        current_time = fields.Datetime.now()
        
        for ticket in self:
            if ticket.served_time:
                if ticket.completed_time:
                    # Service terminé
                    delta = ticket.completed_time - ticket.served_time
                    ticket.service_time = delta.total_seconds() / 60
                elif ticket.state == 'serving':
                    # Service en cours
                    delta = current_time - ticket.served_time
                    ticket.service_time = delta.total_seconds() / 60
                else:
                    ticket.service_time = 0.0
            else:
                ticket.service_time = 0.0

    @api.depends('service_id', 'state', 'ticket_number', 'priority')
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
            service = self.env['queue.service'].browse(service_id)
            if not service.exists():
                continue
                
            # Récupérer tous les tickets en attente pour ce service
            # CORRECTION: Utilisation de la syntaxe correcte pour le tri
            waiting_tickets = service.waiting_ticket_ids.sorted(lambda t: (-self._get_priority_order(t.priority), t.ticket_number))
            
            for ticket in tickets:
                if ticket.state == 'waiting' and ticket in waiting_tickets:
                    # Compter les tickets avant celui-ci (en tenant compte de la priorité)
                    tickets_before = waiting_tickets.filtered(
                        lambda t: (t.priority == 'urgent' and ticket.priority != 'urgent') or
                                (t.priority == 'high' and ticket.priority == 'normal') or
                                (t.priority == ticket.priority and t.ticket_number < ticket.ticket_number)
                    )
                    
                    estimated_minutes = len(tickets_before) * (service.estimated_service_time or 5)
                    ticket.estimated_wait_time = estimated_minutes
                else:
                    ticket.estimated_wait_time = 0.0

    def _get_priority_order(self, priority):
        """Retourne l'ordre numérique de la priorité pour le tri"""
        priority_map = {
            'urgent': 3,
            'high': 2,
            'normal': 1
        }
        return priority_map.get(priority, 1)

    def action_call_next(self):
        """Appeler le prochain ticket"""
        self.ensure_one()
        if self.state != 'waiting':
            raise UserError("Ce ticket n'est pas en attente")
        
        self.write({
            'state': 'called',
            'called_time': fields.Datetime.now()
        })
        
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
        if self.state != 'called':
            raise UserError("Ce ticket n'a pas été appelé")
        
        self.write({
            'state': 'serving',
            'served_time': fields.Datetime.now()
        })
        
        self.message_post(body=f"Service du ticket #{self.ticket_number} commencé")
        return True

    def action_complete_service(self):
        """Terminer le service"""
        self.ensure_one()
        if self.state not in ['called', 'serving']:
            raise UserError("Ce ticket n'est pas en cours de service")
        
        self.write({
            'state': 'served',
            'completed_time': fields.Datetime.now()
        })
        
        # Demander un feedback si email disponible
        if self.customer_email:
            self.action_request_feedback()
        
        self.message_post(body=f"Service du ticket #{self.ticket_number} terminé")
        return True

    def action_cancel(self):
        """Annuler le ticket"""
        self.ensure_one()
        if self.state in ['served', 'cancelled']:
            raise UserError("Ce ticket ne peut plus être annulé")
        
        cancel_reason = "Ticket annulé par l'utilisateur"
        self.action_cancel_ticket(reason=cancel_reason)
        #self.state = 'cancelled'
        #self.message_post(body=f"Ticket #{self.ticket_number} annulé")
        return True

    def action_no_show(self):
        """Marquer comme absent"""
        self.ensure_one()
        if self.state != 'called':
            raise UserError("Ce ticket n'a pas été appelé")
        
        self.state = 'no_show'
        self.message_post(body=f"Ticket #{self.ticket_number} marqué comme absent")
        return True

    def _send_notification(self):
        """Envoyer notification au client"""
        try:
            if self.customer_email:
                # Utiliser le template d'email si disponible
                template = self.env.ref('queue_management.email_ticket_called', raise_if_not_found=False)
                if template:
                    template.send_mail(self.id, force_send=True)
                else:
                    # Créer un email simple
                    mail_values = {
                        'subject': f'Votre ticket #{self.ticket_number} est appelé',
                        'body_html': f'''
                            <p>Bonjour,</p>
                            <p>Votre ticket <strong>#{self.ticket_number}</strong> pour le service 
                            <strong>{self.service_id.name}</strong> est maintenant appelé.</p>
                            <p>Veuillez vous présenter au guichet.</p>
                        ''',
                        'email_to': self.customer_email,
                        'auto_delete': True,
                    }
                    self.env['mail.mail'].sudo().create(mail_values).send()
                
                self.notification_sent = True
                
            # TODO: Intégrer SMS si nécessaire
            if self.customer_phone:
                self._send_sms_notification(f"Votre ticket #{self.ticket_number} est appelé pour {self.service_id.name}")
                
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
        if self.state != 'served':
            return False
        
        try:
            template = self.env.ref('queue_management.email_feedback_request', raise_if_not_found=False)
            if template and self.customer_email:
                template.send_mail(self.id, force_send=True)
            else:
                # Email simple de demande de feedback
                mail_values = {
                    'subject': f'Évaluez votre expérience - Service {self.service_id.name}',
                    'body_html': f'''
                        <p>Bonjour,</p>
                        <p>Nous espérons que votre passage pour le service <strong>{self.service_id.name}</strong> 
                        s'est bien déroulé.</p>
                        <p>Nous aimerions connaître votre avis pour améliorer nos services.</p>
                        <p>Ticket: <strong>#{self.ticket_number}</strong></p>
                    ''',
                    'email_to': self.customer_email,
                    'auto_delete': True,
                }
                self.env['mail.mail'].sudo().create(mail_values).send()
            return True
        except Exception as e:
            _logger.error(f"Erreur demande feedback: {e}")
            return False

    def submit_feedback(self, rating, feedback=''):
        """Soumettre un feedback"""
        self.write({
            'rating': rating,
            'feedback': feedback
        })
        self.message_post(body=f"Feedback reçu: {rating}/5 étoiles")
        return True

    @api.model
    def get_my_ticket_status(self, ticket_number, service_id):
        """Obtenir le statut d'un ticket spécifique (pour les clients)"""
        ticket = self.search([
            ('ticket_number', '=', ticket_number),
            ('service_id', '=', service_id)
        ], limit=1)
        
        if not ticket:
            return {'error': 'Ticket non trouvé'}
        
        # Calculer la position
        tickets_before = self.search_count([
            ('service_id', '=', service_id),
            ('state', '=', 'waiting'),
            ('ticket_number', '<', ticket_number)
        ])
        
        return {
            'ticket_number': ticket.ticket_number,
            'state': ticket.state,
            'position': tickets_before + 1 if ticket.state == 'waiting' else 0,
            'estimated_wait': ticket.estimated_wait_time,
            'service_name': ticket.service_id.name,
            'current_serving': ticket.service_id.current_ticket_number
        }

    # Méthode de mise à jour en lot pour les performances
    @api.model
    def bulk_update_statistics(self, service_ids=None):
        """Mise à jour en lot des statistiques pour améliorer les performances"""
        
        if not service_ids:
            services = self.search([('active', '=', True)])
        else:
            services = self.browse(service_ids)
        
        if not services:
            return {'updated_services': 0}
        
        # Désactiver temporairement le recalcul automatique
        with self.env.norecompute():
            
            # Mise à jour des compteurs de tickets
            for service in services:
                # Synchroniser le compteur avec le dernier ticket
                max_ticket_number = max(service.ticket_ids.mapped('ticket_number') + [0])
                if service.current_ticket_number != max_ticket_number:
                    service.current_ticket_number = max_ticket_number
            
            # Recalculer tous les champs dépendants
            services.modified(['ticket_ids'])
        
        # Forcer le recalcul des champs computed
        services.recompute()
        
        return {
            'updated_services': len(services),
            'timestamp': fields.Datetime.now()
        }

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
            'timestamp': fields.Datetime.now(),
            'integrity_issues_fixed': integrity_report.get('fixes_applied', 0),
            'services_updated': update_report.get('updated_services', 0),
            'old_tickets_cleaned': cleanup_report.get('tickets_count', 0)
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
            ticket_number = data.get('ticket_number')
            service_id = data.get('service_id')
            reason = data.get('reason', '')
            
            # Vérifications de base
            if not ticket_number:
                return {
                    'success': False,
                    'error': 'Numéro de ticket manquant'
                }
            
            if not service_id:
                return {
                    'success': False,
                    'error': 'Service non spécifié'
                }
            
            # Rechercher le ticket
            ticket = self.search([
                ('ticket_number', '=', ticket_number),
                ('service_id', '=', service_id)
            ], limit=1)
            
            if not ticket:
                return {
                    'success': False,
                    'error': f'Ticket #{ticket_number} non trouvé pour ce service'
                }
            
            # Vérifier l'état du ticket
            if ticket.state not in ['waiting', 'called']:
                state_names = {
                    'waiting': 'En Attente',
                    'called': 'Appelé',
                    'serving': 'En Service',
                    'served': 'Terminé',
                    'cancelled': 'Annulé',
                    'no_show': 'Absent'
                }
                current_state = state_names.get(ticket.state, ticket.state)
                
                return {
                    'success': False,
                    'error': f'Impossible d\'annuler un ticket {current_state.lower()}'
                }
            
            # Préparer la raison d'annulation
            cancel_reason = "Annulation client via web"
            if reason and reason.strip():
                cancel_reason = f"Annulation client: {reason.strip()}"
            
            # Effectuer l'annulation
            try:
                ticket.action_cancel_ticket(reason=cancel_reason)
                
                # Log pour traçabilité
                _logger.info(f"Ticket #{ticket_number} (ID: {ticket.id}) annulé via web - Service: {ticket.service_id.name}")
                
                return {
                    'success': True,
                    'message': f'Ticket #{ticket_number} annulé avec succès',
                    'ticket_id': ticket.id,
                    'new_state': 'cancelled'
                }
                
            except UserError as ue:
                _logger.warning(f"Erreur UserError lors de l'annulation du ticket #{ticket_number}: {ue}")
                return {
                    'success': False,
                    'error': str(ue)
                }
            except Exception as e:
                _logger.error(f"Erreur lors de l'annulation du ticket #{ticket_number}: {e}")
                return {
                    'success': False,
                    'error': 'Erreur lors de l\'annulation. Veuillez réessayer.'
                }
                
        except Exception as e:
            _logger.error(f"Erreur dans cancel_ticket_web: {e}")
            return {
                'success': False,
                'error': 'Erreur système. Veuillez réessayer.'
            }

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
            ticket = self.search([
                ('ticket_number', '=', ticket_number),
                ('service_id', '=', service_id)
            ], limit=1)
            
            if not ticket:
                return {
                    'success': False,
                    'error': 'Ticket non trouvé'
                }
            
            # Calculer la position dans la file
            position = 0
            if ticket.state == 'waiting':
                # Compter les tickets avant celui-ci (avec priorité)
                tickets_before = self.search([
                    ('service_id', '=', service_id),
                    ('state', '=', 'waiting'),
                    '|',
                    ('priority', 'in', ['urgent', 'high']),
                    '&',
                    ('priority', '=', ticket.priority),
                    ('ticket_number', '<', ticket_number)
                ])
                position = len(tickets_before) + 1
            
            # Statut détaillé
            state_labels = {
                'waiting': 'En Attente',
                'called': 'Appelé',
                'serving': 'En Service', 
                'served': 'Terminé',
                'cancelled': 'Annulé',
                'no_show': 'Absent'
            }
            
            return {
                'success': True,
                'ticket_number': ticket.ticket_number,
                'state': ticket.state,
                'state_label': state_labels.get(ticket.state, ticket.state),
                'position': position,
                'estimated_wait_time': ticket.estimated_wait_time,
                'service_name': ticket.service_id.name,
                'current_serving': ticket.service_id.current_ticket_number or 0,
                'can_cancel': ticket.state in ['waiting', 'called'],
                'created_time': ticket.created_time.strftime('%d/%m/%Y %H:%M') if ticket.created_time else '',
                'waiting_time': round(ticket.waiting_time, 1) if ticket.waiting_time else 0
            }
            
        except Exception as e:
            _logger.error(f"Erreur dans get_ticket_status_web: {e}")
            return {
                'success': False,
                'error': 'Erreur lors de la récupération du statut'
            }

    def action_cancel_ticket(self, reason=None):
        """
        Version améliorée de action_cancel_ticket avec meilleure gestion d'erreurs
        (Remplace la version existante dans votre code)
        """
        self.ensure_one()
        
        # Vérifier l'état actuel
        if self.state not in ['waiting', 'called']:
            state_names = {
                'waiting': 'En Attente',
                'called': 'Appelé', 
                'serving': 'En Service',
                'served': 'Terminé',
                'cancelled': 'Annulé',
                'no_show': 'Absent'
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
                'state': 'cancelled',
                'completed_time': fields.Datetime.now()
            }
            
            # Ajouter la raison aux notes
            existing_notes = self.notes or ''
            timestamp = fields.Datetime.now().strftime('%d/%m/%Y %H:%M')
            new_note = f"[{timestamp}] {cancel_reason}"
            
            if existing_notes:
                values_to_write['notes'] = f"{existing_notes}\n{new_note}"
            else:
                values_to_write['notes'] = new_note
            
            self.write(values_to_write)
            
            # Message de suivi
            self.message_post(
                body=f"Ticket #{self.ticket_number} annulé",
                subject=f"Annulation ticket #{self.ticket_number}"
            )
            
            # Notification (non bloquante)
            try:
                self._notify_ticket_cancelled(cancel_reason)
            except Exception as e:
                _logger.warning(f"Erreur notification annulation ticket #{self.ticket_number}: {e}")
            
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
                    'subject': f'Ticket #{self.ticket_number} annulé - {self.service_id.name}',
                    'body_html': f'''
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
                    ''',
                    'email_to': self.customer_email,
                    'auto_delete': True,
                }
                self.env['mail.mail'].sudo().create(mail_values).send()
                _logger.info(f"Email d'annulation envoyé à {self.customer_email} pour ticket #{self.ticket_number}")
                
        except Exception as e:
            _logger.error(f"Erreur envoi notification annulation: {e}")