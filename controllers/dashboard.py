# Contrôleur pour les actions AJAX du dashboard
from odoo import http
from odoo.http import request
import json

class QueueDashboardController(http.Controller):

    @http.route('/queue/dashboard/data', type='json', auth='user')
    def get_dashboard_data(self):
        """Endpoint pour récupérer les données du dashboard en AJAX"""
        try:
            service_model = request.env['queue.service']
            data = service_model.get_realtime_stats(use_cache=True)
            return {'success': True, 'data': data}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/queue/dashboard/refresh', type='json', auth='user')  
    def refresh_dashboard(self):
        """Endpoint pour forcer l'actualisation"""
        try:
            service_model = request.env['queue.service']
            service_model.clear_stats_cache()
            data = service_model.get_dashboard_data()
            return {'success': True, 'data': data}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/queue/dashboard/kpis', type='json', auth='user')
    def get_kpis(self):
        """Endpoint pour les KPIs en temps réel"""
        try:
            service_model = request.env['queue.service']
            kpis = service_model.get_realtime_kpis()
            return {'success': True, 'data': kpis}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/queue/dashboard/alerts', type='json', auth='user')
    def get_alerts(self):
        """Endpoint pour les alertes"""
        try:
            service_model = request.env['queue.service']
            alerts = service_model.get_alerts_and_recommendations()
            return {'success': True, 'data': alerts}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/queue/export/<string:format>', type='http', auth='user')
    def export_data(self, format='json'):
        """Endpoint pour l'export de données"""
        try:
            service_model = request.env['queue.service']
            export_data = service_model.export_dashboard_data(format=format)
            
            response = request.make_response(
                export_data['data'] if isinstance(export_data['data'], str) else json.dumps(export_data['data']),
                headers=[
                    ('Content-Type', export_data['content_type']),
                    ('Content-Disposition', f'attachment; filename="{export_data["filename"]}"')
                ]
            )
            return response
            
        except Exception as e:
            return request.make_response(
                f"Erreur lors de l'export: {str(e)}",
                status=500
            )

    @http.route('/queue/maintenance/run', type='json', auth='user')
    def run_maintenance(self, maintenance_type='statistics_update'):
        """Endpoint pour exécuter la maintenance"""
        try:
            if not request.env.user.has_group('queue_management.group_queue_manager'):
                return {'success': False, 'error': 'Permissions insuffisantes'}
            
            service_model = request.env['queue.service']
            
            if maintenance_type == 'full':
                result = service_model.scheduled_data_maintenance()
            elif maintenance_type == 'integrity':
                result = service_model.validate_data_integrity()
            elif maintenance_type == 'stats':
                result = service_model.bulk_update_statistics()
            elif maintenance_type == 'cache':
                service_model.clear_stats_cache()
                result = {'cache_cleared': True}
            else:
                return {'success': False, 'error': 'Type de maintenance invalide'}
            
            return {'success': True, 'result': result}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}