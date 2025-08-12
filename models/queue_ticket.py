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

    @api.depends('created_time', 'called_time', 'state')
    def _compute_waiting_time(self):
        for ticket in self:
            if ticket.state in ['served', 'cancelled', 'no_show'] and ticket.called_time:
                delta = ticket.called_time - ticket.created_time
                ticket.waiting_time = delta.total_seconds() / 60
            else:
                ticket.waiting_time = 0.0

    @api.depends('called_time', 'completed_time')
    def _compute_service_time(self):
        for ticket in self:
            if ticket.called_time and ticket.completed_time:
                delta = ticket.completed_time - ticket.called_time
                ticket.service_time = delta.total_seconds() / 60
            else:
                ticket.service_time = 0.0

    @api.depends('service_id', 'state', 'ticket_number')
    def _compute_estimated_wait(self):
        for ticket in self:
            if ticket.state == 'waiting' and ticket.service_id:
                # Calculer basé sur les tickets en attente avant ce ticket
                tickets_before = self.search_count([
                    ('service_id', '=', ticket.service_id.id),
                    ('state', '=', 'waiting'),
                    ('ticket_number', '<', ticket.ticket_number)
                ])
                estimated_minutes = tickets_before * (ticket.service_id.estimated_service_time or 5)
                ticket.estimated_wait_time = estimated_minutes
            else:
                ticket.estimated_wait_time = 0.0

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