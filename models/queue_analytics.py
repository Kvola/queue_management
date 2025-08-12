# models/queue_analytics.py - Nouveau modèle pour les analyses
from odoo import models, fields, api
from datetime import datetime, timedelta
import json

class QueueAnalytics(models.Model):
    _name = 'queue.analytics'
    _description = 'Analyses des Files d\'Attente'
    _rec_name = 'period'
    _order = 'date desc'

    date = fields.Date('Date', required=True, default=fields.Date.today)
    period = fields.Selection([
        ('daily', 'Quotidien'),
        ('weekly', 'Hebdomadaire'),
        ('monthly', 'Mensuel')
    ], string='Période', required=True, default='daily')
    
    service_id = fields.Many2one('queue.service', 'Service')
    
    # Métriques principales
    total_tickets = fields.Integer('Total Tickets')
    served_tickets = fields.Integer('Tickets Servis')
    cancelled_tickets = fields.Integer('Tickets Annulés')
    no_show_tickets = fields.Integer('Tickets Absents')
    
    # Temps moyens
    avg_waiting_time = fields.Float('Temps d\'Attente Moyen (min)')
    avg_service_time = fields.Float('Temps de Service Moyen (min)')
    
    # Pics d'activité
    peak_hour_start = fields.Float('Début Heure de Pointe')
    peak_hour_end = fields.Float('Fin Heure de Pointe')
    peak_tickets_count = fields.Integer('Tickets à l\'Heure de Pointe')
    
    # Satisfaction
    satisfaction_rate = fields.Float('Taux de Satisfaction (%)')
    
    # Données JSON pour graphiques
    hourly_distribution = fields.Text('Distribution Horaire')
    daily_trend = fields.Text('Tendance Quotidienne')

    @api.model
    def generate_daily_analytics(self, date=None):
        """Générer les analyses quotidiennes"""
        if not date:
            date = fields.Date.today()
        
        services = self.env['queue.service'].search([('active', '=', True)])
        
        for service in services:
            # Récupérer tous les tickets du jour
            tickets = self.env['queue.ticket'].search([
                ('service_id', '=', service.id),
                ('create_date', '>=', datetime.combine(date, datetime.min.time())),
                ('create_date', '<=', datetime.combine(date, datetime.max.time()))
            ])
            
            if not tickets:
                continue
            
            # Calculer les métriques
            served = tickets.filtered(lambda t: t.state == 'served')
            cancelled = tickets.filtered(lambda t: t.state == 'cancelled')
            no_show = tickets.filtered(lambda t: t.state == 'no_show')
            
            avg_wait = sum(t.waiting_time for t in served) / len(served) if served else 0
            avg_service = sum(t.service_time for t in served) / len(served) if served else 0
            satisfaction = len(served) / len(tickets) * 100 if tickets else 0
            
            # Distribution horaire
            hourly_data = {}
            for hour in range(24):
                hour_tickets = tickets.filtered(
                    lambda t: t.create_date.hour == hour
                )
                hourly_data[str(hour)] = len(hour_tickets)
            
            # Trouver l'heure de pointe
            peak_hour = max(hourly_data.items(), key=lambda x: x[1])
            peak_hour_num = int(peak_hour[0])
            peak_count = peak_hour[1]
            
            # Créer ou mettre à jour l'enregistrement analytique
            existing = self.search([
                ('date', '=', date),
                ('period', '=', 'daily'),
                ('service_id', '=', service.id)
            ])
            
            values = {
                'date': date,
                'period': 'daily',
                'service_id': service.id,
                'total_tickets': len(tickets),
                'served_tickets': len(served),
                'cancelled_tickets': len(cancelled),
                'no_show_tickets': len(no_show),
                'avg_waiting_time': round(avg_wait, 2),
                'avg_service_time': round(avg_service, 2),
                'peak_hour_start': peak_hour_num,
                'peak_hour_end': peak_hour_num + 1,
                'peak_tickets_count': peak_count,
                'satisfaction_rate': round(satisfaction, 2),
                'hourly_distribution': json.dumps(hourly_data)
            }
            
            if existing:
                existing.write(values)
            else:
                self.create(values)

    def action_view_details(self):
        """Ouvrir une vue détaillée des analyses avec graphiques et métriques"""
        self.ensure_one()
        
        # Récupérer les tickets associés à cette analyse
        domain = [
            ('service_id', '=', self.service_id.id),
            ('create_date', '>=', datetime.combine(self.date, datetime.min.time())),
            ('create_date', '<=', datetime.combine(self.date, datetime.max.time()))
        ]
        
        # Ajuster le domaine selon la période
        if self.period == 'weekly':
            # Calculer le début et la fin de la semaine
            start_of_week = self.date - timedelta(days=self.date.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            domain = [
                ('service_id', '=', self.service_id.id),
                ('create_date', '>=', datetime.combine(start_of_week, datetime.min.time())),
                ('create_date', '<=', datetime.combine(end_of_week, datetime.max.time()))
            ]
        elif self.period == 'monthly':
            # Calculer le début et la fin du mois
            start_of_month = self.date.replace(day=1)
            if self.date.month == 12:
                end_of_month = start_of_month.replace(year=self.date.year + 1, month=1) - timedelta(days=1)
            else:
                end_of_month = start_of_month.replace(month=self.date.month + 1) - timedelta(days=1)
            domain = [
                ('service_id', '=', self.service_id.id),
                ('create_date', '>=', datetime.combine(start_of_month, datetime.min.time())),
                ('create_date', '<=', datetime.combine(end_of_month, datetime.max.time()))
            ]
        
        # Préparer le contexte avec les données d'analyse
        context = {
            'default_service_id': self.service_id.id,
            'analytics_data': {
                'period': self.period,
                'date': self.date.strftime('%Y-%m-%d'),
                'service_name': self.service_id.name,
                'total_tickets': self.total_tickets,
                'served_tickets': self.served_tickets,
                'cancelled_tickets': self.cancelled_tickets,
                'no_show_tickets': self.no_show_tickets,
                'avg_waiting_time': self.avg_waiting_time,
                'avg_service_time': self.avg_service_time,
                'satisfaction_rate': self.satisfaction_rate,
                'peak_hour_start': self.peak_hour_start,
                'peak_hour_end': self.peak_hour_end,
                'peak_tickets_count': self.peak_tickets_count,
                'hourly_distribution': self.hourly_distribution
            }
        }
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Détails Analyse - %s (%s)') % (self.service_id.name, 
                                                    dict(self._fields['period']._description_selection(self.env))[self.period]),
            'res_model': 'queue.ticket',
            'view_mode': 'tree,form,graph,pivot',
            'views': [
                (False, 'tree'),
                (False, 'form'), 
                (self.env.ref('queue_management.view_queue_ticket_graph_analytics', False).id, 'graph'),
                (self.env.ref('queue_management.view_queue_ticket_pivot_analytics', False).id, 'pivot')
            ],
            'domain': domain,
            'context': context,
            'target': 'current',
            'help': '''
                <p class="o_view_nocontent_smiling_face">
                    Aucun ticket trouvé pour cette période !
                </p>
                <p>
                    Cette vue montre les détails des tickets pour l'analyse sélectionnée.
                    <br/>
                    Utilisez les différentes vues (graphique, pivot) pour analyser les données.
                </p>
            '''
        }

    def action_view_comparative_analysis(self):
        """Comparer cette analyse avec les périodes précédentes"""
        self.ensure_one()
        
        # Calculer les dates de comparaison
        if self.period == 'daily':
            previous_date = self.date - timedelta(days=1)
            comparison_period = 'daily'
        elif self.period == 'weekly':
            previous_date = self.date - timedelta(weeks=1)
            comparison_period = 'weekly'
        else:  # monthly
            if self.date.month == 1:
                previous_date = self.date.replace(year=self.date.year - 1, month=12)
            else:
                previous_date = self.date.replace(month=self.date.month - 1)
            comparison_period = 'monthly'
        
        domain = [
            ('service_id', '=', self.service_id.id),
            ('period', '=', comparison_period),
            ('date', '>=', previous_date - timedelta(days=30)),  # Derniers 30 jours pour contexte
            ('date', '<=', self.date)
        ]
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Analyse Comparative - %s') % self.service_id.name,
            'res_model': 'queue.analytics',
            'view_mode': 'graph,tree,pivot',
            'views': [
                (False, 'graph'),
                (False, 'tree'),
                (False, 'pivot')
            ],
            'domain': domain,
            'context': {
                'default_service_id': self.service_id.id,
                'default_period': self.period,
                'group_by': ['date'],
                'current_analysis_id': self.id
            },
            'target': 'current'
        }

    def action_generate_report(self):
        """Générer un rapport PDF détaillé de l'analyse"""
        self.ensure_one()
        
        return self.env.ref('queue_management.action_report_queue_analytics').report_action(self)

    def action_export_data(self):
        """Exporter les données de l'analyse vers Excel"""
        self.ensure_one()
        
        # Préparer les données pour l'export
        data = {
            'service_name': self.service_id.name,
            'period': dict(self._fields['period']._description_selection(self.env))[self.period],
            'date': self.date,
            'metrics': {
                'total_tickets': self.total_tickets,
                'served_tickets': self.served_tickets,
                'cancelled_tickets': self.cancelled_tickets,
                'no_show_tickets': self.no_show_tickets,
                'avg_waiting_time': self.avg_waiting_time,
                'avg_service_time': self.avg_service_time,
                'satisfaction_rate': self.satisfaction_rate,
            },
            'peak_hours': {
                'start': self.peak_hour_start,
                'end': self.peak_hour_end,
                'tickets_count': self.peak_tickets_count
            }
        }
        
        # Créer un wizard pour l'export
        wizard = self.env['queue.analytics.export.wizard'].create({
            'analytics_id': self.id,
            'export_data': json.dumps(data)
        })
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Exporter Analyse'),
            'res_model': 'queue.analytics.export.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new'
        }

    def action_schedule_analysis(self):
        """Programmer des analyses récurrentes"""
        self.ensure_one()
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Programmer Analyses - %s') % self.service_id.name,
            'res_model': 'queue.analytics.scheduler',
            'view_mode': 'form',
            'context': {
                'default_service_id': self.service_id.id,
                'default_period': self.period,
                'default_base_date': self.date
            },
            'target': 'new'
        }