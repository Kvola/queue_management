# models/queue_config.py
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
class QueueConfig(models.Model):
    _name = 'queue.config'
    _description = 'Configuration File d\'Attente'

    name = fields.Char('Configuration', default='Paramètres Généraux')
    
    # Paramètres généraux
    enable_sms_notifications = fields.Boolean('Activer SMS', default=False)
    enable_email_notifications = fields.Boolean('Activer Email', default=True)
    auto_refresh_interval = fields.Integer('Intervalle refresh (sec)', default=30)
    
    # Paramètres d'affichage
    show_estimated_time = fields.Boolean('Afficher temps estimé', default=True)
    show_queue_position = fields.Boolean('Afficher position', default=True)
    max_display_tickets = fields.Integer('Max tickets affichés', default=10)
    
    # Paramètres business
    allow_ticket_cancellation = fields.Boolean('Permettre annulation', default=True)
    require_customer_info = fields.Boolean('Infos client obligatoires', default=False)