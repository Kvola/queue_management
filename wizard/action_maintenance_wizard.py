# wizard/queue_maintenance_wizard.py

from odoo import models, fields, api, _
from odoo.exceptions import UserError

class QueueMaintenanceWizard(models.TransientModel):
    _name = 'queue.maintenance.wizard'
    _description = 'Assistant de Maintenance des Files d\'Attente'

    maintenance_type = fields.Selection([
        ('data_integrity', 'Vérification Intégrité des Données'),
        ('statistics_update', 'Mise à jour des Statistiques'), 
        ('cache_clear', 'Vider le Cache'),
        ('old_data_cleanup', 'Nettoyage Anciennes Données'),
        ('full_maintenance', 'Maintenance Complète')
    ], string='Type de Maintenance', required=True, default='statistics_update')
    
    days_to_keep = fields.Integer('Jours à Conserver', default=30, 
                                 help="Nombre de jours de données à conserver lors du nettoyage")
    
    service_ids = fields.Many2many('queue.service', string='Services à Traiter',
                                   help="Laisser vide pour traiter tous les services")
    
    auto_fix = fields.Boolean('Correction Automatique', default=True,
                             help="Corriger automatiquement les problèmes détectés")


































    @api.model
    def daily_cancellation_maintenance(self):
        """Maintenance quotidienne des annulations"""
        _logger.info("Début maintenance quotidienne annulations")
        
        config = self.env['queue.config'].get_config()
        
        # 1. Nettoyage automatique si activé
        if config.auto_cleanup_cancelled_tickets:
            cleaned_count = self.env['queue.ticket'].cleanup_old_cancelled_tickets(
                days_to_keep=config.cleanup_delay_days
            )
            _logger.info(f"Nettoyage: {cleaned_count} tickets annulés supprimés")
        
        # 2. Rapport statistique
        stats = self._generate_daily_cancellation_report()
        
        # 3. Alertes automatiques
        self._check_cancellation_trends(stats)
        
        _logger.info("Fin maintenance quotidienne annulations")
        
        return {
            'success': True,
            'cleaned_tickets': cleaned_count if 'cleaned_count' in locals() else 0,
            'stats': stats
        }
    
    def _generate_daily_cancellation_report(self):
        """Générer le rapport quotidien d'annulations"""
        yesterday = fields.Date.today() - timedelta(days=1)
        
        stats = self.env['queue.ticket'].get_cancellation_statistics(
            date_from=yesterday,
            date_to=yesterday
        )
        
        # Envoyer le rapport aux administrateurs si significatif
        if stats['total_cancelled'] > 0:
            self._send_daily_report(stats, yesterday)
        
        return stats
    
    def _send_daily_report(self, stats, date):
        """Envoyer le rapport quotidien"""
        try:
            admin_users = self.env.ref('queue_management.group_queue_manager').users
            
            report_html = f"""
                <h2>Rapport quotidien d'annulations - {date.strftime('%d/%m/%Y')}</h2>
                <h3>Statistiques globales</h3>
                <ul>
                    <li>Total annulations: <strong>{stats['total_cancelled']}</strong></li>
                </ul>
                
                <h3>Par type d'annulation</h3>
                <ul>
                    {''.join([f'<li>{k}: {v}</li>' for k, v in stats['by_type'].items()])}
                </ul>
                
                <h3>Par service</h3>
                <ul>
                    {''.join([f'<li>{k}: {v}</li>' for k, v in stats['by_service'].items()])}
                </ul>
            """
            
            for user in admin_users:
                if user.email:
                    self.env['mail.mail'].sudo().create({
                        'subject': f'Rapport quotidien annulations - {date.strftime("%d/%m/%Y")}',
                        'body_html': report_html,
                        'email_to': user.email,
                        'auto_delete': True,
                    }).send()
                    
        except Exception as e:
            _logger.error(f"Erreur envoi rapport quotidien: {e}")

















































    def action_run_maintenance(self):
        """Exécuter la maintenance sélectionnée"""
        self.ensure_one()
        
        service_model = self.env['queue.service']
        results = {}
        
        try:
            if self.maintenance_type == 'data_integrity':
                results = service_model.validate_data_integrity()
                
            elif self.maintenance_type == 'statistics_update':
                service_ids = self.service_ids.ids if self.service_ids else None
                results = service_model.bulk_update_statistics(service_ids)
                
            elif self.maintenance_type == 'cache_clear':
                service_model.clear_stats_cache()
                results = {'cache_cleared': True}
                
            elif self.maintenance_type == 'old_data_cleanup':
                results = service_model.cleanup_old_data(self.days_to_keep)
                
            elif self.maintenance_type == 'full_maintenance':
                results = service_model.scheduled_data_maintenance()
            
            # Afficher les résultats
            return self._show_maintenance_results(results)
            
        except Exception as e:
            raise UserError(_("Erreur lors de la maintenance: %s") % str(e))

    def _show_maintenance_results(self, results):
        """Afficher les résultats de la maintenance"""
        
        message_lines = []
        
        if 'fixes_applied' in results:
            message_lines.append(f"✅ {results['fixes_applied']} corrections appliquées")
        
        if 'updated_services' in results:
            message_lines.append(f"📊 {results['updated_services']} services mis à jour")
        
        if 'tickets_count' in results:
            message_lines.append(f"🗑️ {results['tickets_count']} anciens tickets supprimés")
        
        if 'cache_cleared' in results:
            message_lines.append("🔄 Cache vidé avec succès")
        
        if 'issues_details' in results and results['issues_details']:
            message_lines.append(f"⚠️ Problèmes détectés:")
            for issue in results['issues_details'][:5]:  # Limiter à 5 pour l'affichage
                message_lines.append(f"  • {issue}")
        
        message = '\n'.join(message_lines) if message_lines else "Maintenance terminée sans action requise"
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Maintenance Terminée',
                'message': message,
                'type': 'success',
                'sticky': True
            }
        }

# wizard/queue_stats_wizard.py
class QueueStatsWizard(models.TransientModel):
    _name = 'queue.stats.wizard'
    _description = 'Assistant de Génération de Rapports'

    report_type = fields.Selection([
        ('daily', 'Rapport Quotidien'),
        ('weekly', 'Rapport Hebdomadaire'),
        ('monthly', 'Rapport Mensuel'),
        ('custom', 'Période Personnalisée')
    ], string='Type de Rapport', required=True, default='daily')
    
    date_from = fields.Date('Date de Début', default=fields.Date.today)
    date_to = fields.Date('Date de Fin', default=fields.Date.today)
    
    service_ids = fields.Many2many('queue.service', string='Services',
                                   help="Laisser vide pour tous les services")
    
    include_charts = fields.Boolean('Inclure Graphiques', default=True)
    include_details = fields.Boolean('Inclure Détails', default=True)
    export_format = fields.Selection([
        ('pdf', 'PDF'),
        ('excel', 'Excel'), 
        ('json', 'JSON')
    ], string='Format Export', default='pdf')

    @api.onchange('report_type')
    def _onchange_report_type(self):
        """Ajuster les dates selon le type de rapport"""
        today = fields.Date.today()
        
        if self.report_type == 'daily':
            self.date_from = today
            self.date_to = today
        elif self.report_type == 'weekly':
            # Semaine courante (lundi à dimanche)
            days_since_monday = today.weekday()
            monday = today - timedelta(days=days_since_monday)
            self.date_from = monday
            self.date_to = today
        elif self.report_type == 'monthly':
            # Mois courant
            self.date_from = today.replace(day=1)
            self.date_to = today

    def action_generate_report(self):
        """Générer le rapport demandé"""
        self.ensure_one()
        
        service_model = self.env['queue.service']
        
        # Générer les données du rapport
        report_data = service_model.generate_performance_report(
            date_from=self.date_from,
            date_to=self.date_to,
            service_ids=self.service_ids.ids if self.service_ids else None
        )
        
        if self.export_format == 'json':
            # Export JSON direct
            export_data = service_model.export_dashboard_data(
                format='json', 
                include_details=self.include_details
            )
            
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content?model=queue.stats.wizard&id={self.id}&field=report_data&download=true&filename={export_data["filename"]}',
                'target': 'self'
            }
        
        elif self.export_format == 'pdf':
            # Générer rapport PDF
            return self._generate_pdf_report(report_data)
        
        elif self.export_format == 'excel':
            # Générer rapport Excel
            return self._generate_excel_report(report_data)

    def _generate_pdf_report(self, report_data):
        """Générer un rapport PDF"""
        
        # Utiliser le moteur de rapport Odoo
        return self.env.ref('queue_management.action_queue_performance_report').report_action(
            self, data={
                'report_data': report_data,
                'wizard_data': {
                    'date_from': self.date_from,
                    'date_to': self.date_to,
                    'service_names': ', '.join(self.service_ids.mapped('name')) if self.service_ids else 'Tous les services'
                }
            }
        )

    def _generate_excel_report(self, report_data):
        """Générer un rapport Excel"""
        
        # TODO: Implémenter avec xlsxwriter
        # Pour l'instant, convertir en CSV
        csv_data = self.env['queue.service'].export_dashboard_data(
            format='csv',
            include_details=self.include_details
        )
        
        return {
            'type': 'ir.actions.act_url', 
            'url': f'/web/content?data={csv_data["data"]}&filename={csv_data["filename"]}&mimetype={csv_data["content_type"]}',
            'target': 'self'
        }

# Action serveur pour la maintenance automatique
class QueueMaintenanceAction(models.Model):
    _name = 'queue.maintenance.action'
    _description = 'Action de Maintenance Automatique'

    name = fields.Char('Nom', required=True)
    maintenance_type = fields.Selection([
        ('daily_stats', 'Statistiques Quotidiennes'),
        ('weekly_cleanup', 'Nettoyage Hebdomadaire'),
        ('monthly_archive', 'Archivage Mensuel'),
        ('integrity_check', 'Vérification Intégrité')
    ], string='Type', required=True)
    
    schedule = fields.Selection([
        ('hourly', 'Toutes les heures'),
        ('daily', 'Quotidien'),
        ('weekly', 'Hebdomadaire'),
        ('monthly', 'Mensuel')
    ], string='Fréquence', required=True)
    
    active = fields.Boolean('Actif', default=True)
    last_run = fields.Datetime('Dernière Exécution')
    next_run = fields.Datetime('Prochaine Exécution')
    
    def execute_maintenance(self):
        """Exécuter la maintenance"""
        for action in self:
            try:
                service_model = self.env['queue.service']
                
                if action.maintenance_type == 'daily_stats':
                    result = service_model.bulk_update_statistics()
                elif action.maintenance_type == 'weekly_cleanup':
                    result = service_model.cleanup_old_data(days_to_keep=7)
                elif action.maintenance_type == 'monthly_archive':
                    result = service_model.cleanup_old_data(days_to_keep=90)
                elif action.maintenance_type == 'integrity_check':
                    result = service_model.validate_data_integrity()
                
                action.last_run = fields.Datetime.now()
                action._compute_next_run()
                
                _logger.info(f"Maintenance {action.name} exécutée: {result}")
                
            except Exception as e:
                _logger.error(f"Erreur maintenance {action.name}: {e}")

    @api.depends('schedule', 'last_run')
    def _compute_next_run(self):
        """Calculer la prochaine exécution"""
        for action in self:
            if not action.last_run:
                action.next_run = fields.Datetime.now()
                continue
            
            if action.schedule == 'hourly':
                action.next_run = action.last_run + timedelta(hours=1)
            elif action.schedule == 'daily':
                action.next_run = action.last_run + timedelta(days=1)
            elif action.schedule == 'weekly':
                action.next_run = action.last_run + timedelta(weeks=1)
            elif action.schedule == 'monthly':
                action.next_run = action.last_run + timedelta(days=30)
            else:
                action.next_run = action.last_run + timedelta(days=1)

# Action côté serveur pour l'interface
class QueueDashboardActions(models.Model):
    _name = 'queue.dashboard.actions'
    _description = 'Actions du Dashboard'

    @api.model
    def refresh_all_data(self):
        """Actualiser toutes les données du dashboard"""
        service_model = self.env['queue.service']
        
        # Vider le cache
        service_model.clear_stats_cache()
        
        # Mise à jour des statistiques
        update_result = service_model.bulk_update_statistics()
        
        # Récupérer les nouvelles données
        dashboard_data = service_model.get_dashboard_data()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'queue_dashboard_refresh',
            'params': {
                'dashboard_data': dashboard_data,
                'update_info': update_result
            }
        }

    @api.model
    def export_current_status(self, export_format='json'):
        """Exporter le statut actuel"""
        service_model = self.env['queue.service']
        
        export_data = service_model.export_dashboard_data(
            format=export_format,
            include_details=True
        )
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/queue/export/{export_format}',
            'target': 'self'
        }

    @api.model 
    def get_system_health(self):
        """Vérifier la santé globale du système"""
        service_model = self.env['queue.service']
        
        # Vérifications de base
        health_checks = {
            'services_active': len(service_model.search([('active', '=', True)])),
            'services_open': len(service_model.search([('active', '=', True), ('is_open', '=', True)])),
            'total_waiting': len(self.env['queue.ticket'].search([('state', '=', 'waiting')])),
            'total_serving': len(self.env['queue.ticket'].search([('state', '=', 'serving')])),
            'data_integrity': service_model.validate_data_integrity(),
            'alerts': service_model.get_alerts_and_recommendations()
        }
        
        # Déterminer le statut global
        if health_checks['alerts']['alert_count'] > 5:
            system_status = 'critical'
        elif health_checks['alerts']['alert_count'] > 2:
            system_status = 'warning'  
        elif health_checks['data_integrity']['issues_found'] > 0:
            system_status = 'issues'
        else:
            system_status = 'healthy'
        
        health_checks['system_status'] = system_status
        health_checks['timestamp'] = fields.Datetime.now()
        
        return health_checks