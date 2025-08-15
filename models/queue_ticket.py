# models/queue_ticket.py
from odoo import models, fields, api, _
from odoo.exceptions import UserError
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
    estimated_wait_time = fields.Float('Temps d\'attente estimé', compute='_compute_estimated_wait')
    
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

    @api.model
    def create(self, vals):
        """Override create pour générer automatiquement le numéro de ticket"""
        if 'ticket_number' not in vals and 'service_id' in vals:
            service = self.env['queue.service'].browse(vals['service_id'])
            if service.exists():
                vals['ticket_number'] = service.next_ticket_number
                # Incrémenter le compteur du service
                service.next_ticket_number += 1
        return super(QueueTicket, self).create(vals)
    
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
        
        self.state = 'cancelled'
        self.message_post(body=f"Ticket #{self.ticket_number} annulé")
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


    def action_cancel_ticket(self, reason=None):
        """Action pour annuler un ticket - VERSION CORRIGÉE"""
        self.ensure_one()
        
        # Vérifier l'état actuel
        if self.state not in ['waiting', 'called']:
            raise UserError(f"Ce ticket (état: {dict(self._fields['state'].selection)[self.state]}) ne peut plus être annulé")
        
        # Préparer la raison
        if not reason:
            cancel_reason = "Ticket annulé"
        else:
            cancel_reason = reason.strip()
        
        # Effectuer l'annulation
        values_to_write = {
            'state': 'cancelled',
            'completed_time': fields.Datetime.now()
        }
        
        # Ajouter la raison aux notes existantes
        existing_notes = self.notes or ''
        if existing_notes:
            values_to_write['notes'] = f"{existing_notes}\n{cancel_reason}"
        else:
            values_to_write['notes'] = cancel_reason
        
        self.write(values_to_write)
        
        # Message de suivi
        self.message_post(body=f"Ticket #{self.ticket_number} annulé. Raison: {cancel_reason}")
        
        # Notifier si nécessaire (méthode optionnelle)
        try:
            self._notify_ticket_cancelled(cancel_reason)
        except Exception as e:
            _logger.warning(f"Erreur lors de la notification d'annulation: {e}")
        
        return True
        
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