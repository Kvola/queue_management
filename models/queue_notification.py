# models/queue_notification.py - Nouveau modèle pour les notifications
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
class QueueNotification(models.Model):
    _name = 'queue.notification'
    _description = 'Notifications File d\'Attente'
    _order = 'create_date desc'

    ticket_id = fields.Many2one('queue.ticket', 'Ticket', required=True, ondelete='cascade')
    notification_type = fields.Selection([
        ('sms', 'SMS'),
        ('email', 'Email'),
        ('push', 'Notification Push')
    ], string='Type', required=True)
    
    status = fields.Selection([
        ('pending', 'En Attente'),
        ('sent', 'Envoyé'),
        ('failed', 'Échec'),
        ('delivered', 'Livré')
    ], string='Statut', default='pending')
    
    message = fields.Text('Message')
    recipient = fields.Char('Destinataire')
    error_message = fields.Text('Message d\'Erreur')
    sent_date = fields.Datetime('Date d\'Envoi')
    delivered_date = fields.Datetime('Date de Livraison')

    def send_notification(self):
        """Envoyer la notification"""
        for notification in self:
            try:
                if notification.notification_type == 'email':
                    notification._send_email()
                elif notification.notification_type == 'sms':
                    notification._send_sms()
                elif notification.notification_type == 'push':
                    notification._send_push()
                    
                notification.write({
                    'status': 'sent',
                    'sent_date': fields.Datetime.now()
                })
                
            except Exception as e:
                notification.write({
                    'status': 'failed',
                    'error_message': str(e)
                })

    def _send_email(self):
        """Envoyer notification par email"""
        if not self.ticket_id.customer_email:
            raise Exception("Pas d'email client")
        
        self.env['mail.mail'].create({
            'subject': f'Notification - {self.ticket_id.service_id.name}',
            'body_html': f'<p>{self.message}</p>',
            'email_to': self.ticket_id.customer_email,
            'auto_delete': True,
        }).send()

    def _send_sms(self):
        """Envoyer notification SMS (à personnaliser)"""
        if not self.ticket_id.customer_phone:
            raise Exception("Pas de téléphone client")
        
        # Intégration avec votre service SMS
        # Exemple avec un service générique:
        pass

    def _send_push(self):
        """Envoyer notification push (à personnaliser)"""
        # Intégration avec votre service de push notifications
        pass