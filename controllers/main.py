# controllers/main.py - VERSION CORRIGÉE IMPRESSION
from odoo import http, fields
from odoo.http import request
from datetime import datetime
import json
import logging

_logger = logging.getLogger(__name__)

# Routes additionnelles pour la robustesse
class QueueControllerFallback(http.Controller):
    """Contrôleur de secours avec routes simplifiées"""
    
    @http.route('/queue/simple', type='http', auth='public', website=True)
    def simple_queue_page(self, **kwargs):
        """Version ultra-simplifiée sans templates complexes"""
        try:
            services = request.env['queue.service'].sudo().search([('active', '=', True)])
            
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Files d'Attente</title>
                <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
            </head>
            <body>
                <div class="container mt-4">
                    <h1 class="text-center mb-4">Files d'Attente</h1>
                    <div class="row">
            """
            
            for service in services:
                waiting_count = len(service.waiting_ticket_ids) if hasattr(service, 'waiting_ticket_ids') else 0
                
                html += f"""
                        <div class="col-md-6 mb-3">
                            <div class="card">
                                <div class="card-body">
                                    <h5 class="card-title">{service.name}</h5>
                                    <p class="card-text">En attente: {waiting_count}</p>
                                    <form method="post" action="/queue/take_ticket_http">
                                        <input type="hidden" name="service_id" value="{service.id}">
                                        <button type="submit" class="btn btn-primary {'w-100' if service.is_open else 'w-100 disabled'}">
                                            {'Prendre un ticket' if service.is_open else 'Service fermé'}
                                        </button>
                                    </form>
                                </div>
                            </div>
                        </div>
                """
            
            html += """
                    </div>
                </div>
                <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
            </body>
            </html>
            """
            
            return request.make_response(html, headers={'Content-Type': 'text/html; charset=utf-8'})
            
        except Exception as e:
            _logger.error(f"Erreur page simple: {e}")
            return request.make_response(
                f"<h1>Erreur: {str(e)}</h1><p>Vérifiez la configuration de votre module.</p>",
                headers={'Content-Type': 'text/html; charset=utf-8'}
            )


class QueueController(http.Controller):
    def _generate_ticket_number(self, service):
        """Générer le prochain numéro de ticket pour un service"""
        try:
            # Méthode 1: Utiliser le next_ticket_number du service
            if hasattr(service, 'next_ticket_number') and service.next_ticket_number:
                next_number = service.next_ticket_number
                # Incrémenter pour le prochain
                service.sudo().write({'next_ticket_number': next_number + 1})
                return next_number
            
            # Méthode 2: Trouver le maximum + 1
            last_ticket = request.env['queue.ticket'].sudo().search([
                ('service_id', '=', service.id)
            ], order='ticket_number desc', limit=1)
            
            if last_ticket:
                next_number = last_ticket.ticket_number + 1
            else:
                next_number = 1
            
            # Mettre à jour le service
            service.sudo().write({'next_ticket_number': next_number + 1})
            return next_number
            
        except Exception as e:
            _logger.error(f"Erreur génération numéro ticket: {e}")
            # Fallback: timestamp-based
            import time
            return int(time.time()) % 10000

    # ROUTES D'IMPRESSION CORRIGÉES
    @http.route('/queue/print_ticket/<int:ticket_number>/<int:service_id>', type='http', auth='public', website=False, csrf=False)
    def print_ticket(self, ticket_number, service_id, auto_print=None, auto_close=None, **kwargs):
        """Version imprimable du ticket - ROUTE PRINCIPALE"""
        try:
            _logger.info(f"Impression ticket #{ticket_number} pour service {service_id}")
            
            # Rechercher le ticket
            ticket = request.env['queue.ticket'].sudo().search([
                ('ticket_number', '=', ticket_number),
                ('service_id', '=', service_id)
            ], limit=1)
            
            service = request.env['queue.service'].sudo().browse(service_id)
            
            if not ticket or not service.exists():
                error_html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Ticket Non Trouvé</title>
                    <meta charset="utf-8">
                </head>
                <body>
                    <div style="text-align: center; padding: 50px;">
                        <h2>❌ Ticket Non Trouvé</h2>
                        <p>Ticket #{ticket_number} pour le service {service.name if service.exists() else 'inconnu'} introuvable.</p>
                        <button onclick="window.close()">Fermer</button>
                    </div>
                </body>
                </html>
                """
                return request.make_response(error_html, headers={'Content-Type': 'text/html; charset=utf-8'})
            
            # Calculer la position
            position = 1
            if ticket.state == 'waiting':
                try:
                    tickets_before_count = request.env['queue.ticket'].sudo().search_count([
                        ('service_id', '=', service.id),
                        ('state', '=', 'waiting'),
                        ('ticket_number', '<', ticket.ticket_number)
                    ])
                    position = tickets_before_count + 1
                except Exception as e:
                    _logger.warning(f"Erreur calcul position: {e}")
                    position = 1
            
            # Template d'impression optimisé
            print_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Ticket #{ticket.ticket_number}</title>
                <meta charset="utf-8">
                <style>
                    @media print {{
                        @page {{ margin: 0; }}
                        body {{ margin: 10px; }}
                    }}
                    body {{
                        font-family: 'Courier New', monospace;
                        width: 58mm;
                        margin: 0 auto;
                        text-align: center;
                        font-size: 12px;
                        line-height: 1.2;
                    }}
                    .header {{
                        border-bottom: 2px dashed #000;
                        padding-bottom: 10px;
                        margin-bottom: 10px;
                    }}
                    .ticket-number {{
                        font-size: 24px;
                        font-weight: bold;
                        margin: 10px 0;
                    }}
                    .service-name {{
                        font-size: 14px;
                        font-weight: bold;
                        margin: 5px 0;
                    }}
                    .info {{
                        margin: 5px 0;
                        font-size: 11px;
                    }}
                    .footer {{
                        border-top: 2px dashed #000;
                        padding-top: 10px;
                        margin-top: 10px;
                        font-size: 10px;
                    }}
                    .qr-code {{
                        margin: 10px 0;
                    }}
                </style>
                {"<script>window.onload=function(){window.print();}</script>" if auto_print else ""}
                {"<script>window.onafterprint=function(){window.close();}</script>" if auto_close else ""}
            </head>
            <body>
                <div class="header">
                    <div class="service-name">{service.name}</div>
                    <div class="ticket-number">#{ticket.ticket_number}</div>
                </div>
                
                <div class="info">
                    <div><strong>Position:</strong> {position}</div>
                    <div><strong>Temps estimé:</strong> ~{ticket.estimated_wait_time or (position * 5)} min</div>
                    <div><strong>État:</strong> {dict(ticket._fields['state'].selection).get(ticket.state, ticket.state)}</div>
                </div>
                
                <div class="info">
                    <div><strong>Date:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
                    {f"<div><strong>Client:</strong> {ticket.customer_name}</div>" if ticket.customer_name else ""}
                </div>
                
                <div class="qr-code">
                    <img src="https://api.qrserver.com/v1/create-qr-code/?size=100x100&data={request.httprequest.host_url}queue/my_ticket/{ticket.ticket_number}/{service.id}" 
                         alt="QR Code" style="width: 60px; height: 60px;">
                </div>
                
                <div class="footer">
                    <div>Présentez-vous quand</div>
                    <div>votre numéro sera appelé</div>
                    <div style="margin-top: 5px;">Suivi: {request.httprequest.host_url.replace('http://', '').replace('https://', '').split('/')[0]}</div>
                </div>
                
                {"<script>setTimeout(function(){window.close();}, 3000);</script>" if auto_close else ""}
            </body>
            </html>
            """
            
            return request.make_response(print_html, headers={
                'Content-Type': 'text/html; charset=utf-8',
                'Cache-Control': 'no-cache, no-store, must-revalidate'
            })
            
        except Exception as e:
            _logger.error(f"Erreur impression ticket: {e}")
            error_html = f"""
            <!DOCTYPE html>
            <html>
            <head><title>Erreur Impression</title><meta charset="utf-8"></head>
            <body>
                <div style="text-align: center; padding: 20px;">
                    <h3>❌ Erreur d'Impression</h3>
                    <p>Erreur: {str(e)}</p>
                    <button onclick="window.close()">Fermer</button>
                </div>
            </body>
            </html>
            """
            return request.make_response(error_html, headers={'Content-Type': 'text/html; charset=utf-8'})

    @http.route('/queue/print_ticket_minimal/<int:ticket_id>', type='http', auth='public', website=False, csrf=False)
    def print_ticket_minimal(self, ticket_id, **kwargs):
        """Version ultra-minimaliste pour impression directe par ID"""
        try:
            ticket = request.env['queue.ticket'].sudo().browse(ticket_id)
            if not ticket.exists():
                return request.make_response("Ticket non trouvé", headers={'Content-Type': 'text/plain'})
            
            # Rediriger vers la route principale
            return request.redirect(f'/queue/print_ticket/{ticket.ticket_number}/{ticket.service_id.id}?auto_print=1&auto_close=1')
            
        except Exception as e:
            _logger.error(f"Erreur print minimal: {e}")
            return request.make_response(f"Erreur: {str(e)}", headers={'Content-Type': 'text/plain'})

    @http.route('/queue/print_popup/<int:ticket_number>/<int:service_id>', type='http', auth='public', website=False, csrf=False)
    def print_ticket_popup(self, ticket_number, service_id, **kwargs):
        """Ouvre le ticket dans une popup pour impression"""
        popup_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Impression Ticket</title>
            <meta charset="utf-8">
        </head>
        <body>
            <script>
                var printUrl = '/queue/print_ticket/{ticket_number}/{service_id}?auto_print=1&auto_close=1';
                var printWindow = window.open(printUrl, 'print', 'width=400,height=600,scrollbars=yes');
                
                if (!printWindow) {{
                    alert('Popup bloqué. Redirection vers la page d\\'impression...');
                    window.location.href = printUrl;
                }} else {{
                    printWindow.focus();
                    // Fermer cette fenêtre après 2 secondes
                    setTimeout(function() {{
                        window.close();
                    }}, 2000);
                }}
            </script>
            <div style="text-align: center; padding: 20px;">
                <p>Ouverture de la fenêtre d'impression...</p>
                <p>Si rien ne se passe, <a href="/queue/print_ticket/{ticket_number}/{service_id}" target="_blank">cliquez ici</a></p>
            </div>
        </body>
        </html>
        """
        return request.make_response(popup_html, headers={'Content-Type': 'text/html; charset=utf-8'})

    # ROUTES PRINCIPALES
    @http.route('/queue', type='http', auth='public', website=True)
    def queue_main(self, **kwargs):
        """Page principale des files d'attente"""
        try:
            services = request.env['queue.service'].sudo().search([('active', '=', True)])
            
            # Force le recalcul des statistiques si nécessaire
            for service in services:
                try:
                    if not hasattr(service, 'waiting_count') or service.waiting_count < 0:
                        service._compute_waiting_count()
                    if not hasattr(service, 'avg_waiting_time') or service.avg_waiting_time < 0:
                        service._compute_avg_waiting_time()
                except Exception as e:
                    _logger.warning(f"Erreur calcul stats pour service {service.id}: {e}")
            
            return request.render('queue_management.queue_home_template', {
                'services': services
            })
            
        except Exception as e:
            _logger.error(f"Erreur page principale: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors du chargement de la page principale'
            })
    
    @http.route('/queue/service/<int:service_id>', type='http', auth='public', website=True)
    def queue_service_detail(self, service_id, **kwargs):
        """Détail d'un service avec file d'attente"""
        try:
            service = request.env['queue.service'].sudo().browse(service_id)
            if not service.exists():
                return request.render('queue_management.error_template', {
                    'error_message': 'Service non trouvé'
                })
            
            # Vérifier si le service est fermé
            if not service.is_open:
                return request.render('queue_management.service_closed_template', {
                    'service': service
                })
            
            # Récupérer les tickets en attente de manière sécurisée
            try:
                waiting_tickets = service.waiting_ticket_ids.sorted('ticket_number')
            except Exception as e:
                _logger.warning(f"Erreur récupération tickets: {e}")
                waiting_tickets = request.env['queue.ticket'].sudo().search([
                    ('service_id', '=', service.id),
                    ('state', '=', 'waiting')
                ]).sorted('ticket_number')
            
            return request.render('queue_management.queue_service_template', {
                'service': service,
                'waiting_tickets': waiting_tickets
            })
            
        except Exception as e:
            _logger.error(f"Erreur détail service {service_id}: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors du chargement du service'
            })
    
    @http.route('/queue/take_ticket_http', type='http', auth='public', methods=['POST'], csrf=False, website=True)
    def take_ticket_http(self, service_id, customer_phone='', customer_email='', customer_name='', **kwargs):
        """Prendre un ticket via formulaire HTTP - VERSION ULTRA-SÉCURISÉE"""

        def create_error_response(message, service=None):
            """Créer une réponse d'erreur sans dépendre des templates"""
            try:
                # Essayer d'abord le template normal
                context = {'error_message': message}
                if service:
                    context['service'] = service
                return request.render('queue_management.error_template', context)
            except Exception as template_error:
                _logger.error(f"Template error_template échoué: {template_error}")
                # Fallback HTML direct
                service_info = f"<p><strong>Service:</strong> {service.name}</p>" if service else ""
                error_html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Erreur - File d'Attente</title>
                    <meta charset="utf-8">
                    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
                </head>
                <body>
                    <div class="container mt-4">
                        <div class="alert alert-danger">
                            <h4>❌ Erreur</h4>
                            <p>{message}</p>
                            {service_info}
                            <div class="mt-3">
                                <a href="/queue" class="btn btn-primary">Retour à l'accueil</a>
                                <a href="/queue/simple" class="btn btn-secondary">Interface simple</a>
                            </div>
                        </div>
                    </div>
                </body>
                </html>
                """
                return request.make_response(error_html, headers={'Content-Type': 'text/html; charset=utf-8'})
        
        try:
            # Validation des paramètres
            if not service_id:
                return create_error_response('Service non spécifié')
            
            try:
                service_id = int(service_id)
            except (ValueError, TypeError):
                return create_error_response('ID de service invalide')
            
            service = request.env['queue.service'].sudo().browse(service_id)
            if not service.exists():
                return create_error_response('Service non trouvé')
            
            if not service.is_open:
                return create_error_response('Service actuellement fermé', service)
            
            # Préparer les données
            ticket_data = {'service_id': service.id}
            
            if customer_phone and customer_phone.strip():
                ticket_data['customer_phone'] = customer_phone.strip()[:20]
            if customer_email and customer_email.strip():
                ticket_data['customer_email'] = customer_email.strip()[:100]
            if customer_name and customer_name.strip():
                ticket_data['customer_name'] = customer_name.strip()[:50]
            
            # Créer le ticket
            ticket = request.env['queue.ticket'].sudo().create(ticket_data)
            
            if not ticket or not ticket.exists():
                return create_error_response('Impossible de créer le ticket')
            
            _logger.info(f"Ticket #{ticket.ticket_number} créé avec succès pour service {service.name}")
            
            # Redirection vers confirmation
            return request.redirect(f'/queue/ticket_confirmation/{ticket.id}')
            
        except Exception as e:
            _logger.error(f"Erreur création ticket: {e}")
            return create_error_response('Une erreur est survenue lors de la création du ticket')

    @http.route('/queue/ticket_confirmation/<int:ticket_id>', type='http', auth='public', website=True)
    def ticket_confirmation(self, ticket_id, **kwargs):
        """Page de confirmation après création d'un ticket"""
        try:
            ticket = request.env['queue.ticket'].sudo().browse(ticket_id)
            if not ticket.exists():
                return request.render('queue_management.error_template', {
                    'error_message': 'Ticket non trouvé'
                })
            
            # Calculer la position de manière sécurisée
            position = 0
            if ticket.state == 'waiting':
                try:
                    tickets_before_count = request.env['queue.ticket'].sudo().search_count([
                        ('service_id', '=', ticket.service_id.id),
                        ('state', '=', 'waiting'),
                        ('ticket_number', '<', ticket.ticket_number)
                    ])
                    position = tickets_before_count + 1
                except Exception as e:
                    _logger.warning(f"Erreur calcul position: {e}")
                    position = 1
            
            return request.render('queue_management.ticket_confirmation_template', {
                'ticket': ticket,
                'service': ticket.service_id,
                'position': position,
                'track_url': f'/queue/my_ticket/{ticket.ticket_number}/{ticket.service_id.id}'
            })
            
        except Exception as e:
            _logger.error(f"Erreur confirmation ticket {ticket_id}: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors de l\'affichage de la confirmation'
            })

    @http.route('/queue/my_ticket/<int:ticket_number>/<int:service_id>', 
                type='http', auth='public', website=True)
    def my_ticket_status(self, ticket_number, service_id, **kwargs):
        """Page de suivi d'un ticket spécifique"""
        try:
            # Validation des paramètres
            if not ticket_number or not service_id:
                return request.render('queue_management.error_template', {
                    'error_message': 'Paramètres manquants'
                })
            
            # Recherche sécurisée du ticket
            ticket = request.env['queue.ticket'].sudo().search([
                ('ticket_number', '=', ticket_number),
                ('service_id', '=', service_id)
            ], limit=1)
            
            if not ticket:
                return request.render('queue_management.ticket_not_found_template', {
                    'ticket_number': ticket_number,
                    'service_id': service_id
                })
            
            # Calculer la position de manière défensive
            position = 0
            if ticket.state == 'waiting':
                try:
                    tickets_before = request.env['queue.ticket'].sudo().search([
                        ('service_id', '=', ticket.service_id.id),
                        ('state', '=', 'waiting'),
                        ('ticket_number', '<', ticket.ticket_number)
                    ])
                    position = len(tickets_before) + 1
                    
                    # Mettre à jour le temps d'attente si nécessaire
                    if position > 0 and hasattr(ticket.service_id, 'estimated_service_time'):
                        estimated_wait = position * (ticket.service_id.estimated_service_time or 5)
                        if abs((ticket.estimated_wait_time or 0) - estimated_wait) > 2:
                            ticket.sudo().write({'estimated_wait_time': estimated_wait})
                except Exception as e:
                    _logger.warning(f"Erreur calcul position pour ticket {ticket_number}: {e}")
                    position = 1
            
            return request.render('queue_management.my_ticket_template', {
                'ticket': ticket,
                'service': ticket.service_id,
                'position': position
            })
            
        except Exception as e:
            _logger.error(f"Erreur suivi ticket {ticket_number}/{service_id}: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors du chargement des informations du ticket'
            })

    # API JSON ENDPOINTS
    @http.route('/queue/take_ticket', type='json', auth='public', methods=['POST'], csrf=False)
    def take_ticket_json(self, service_id, customer_phone='', customer_email='', customer_name='', **kwargs):
        """Prendre un ticket via API JSON"""
        try:
            if not service_id:
                return {'success': False, 'error': 'ID du service requis'}
            
            service = request.env['queue.service'].sudo().browse(int(service_id))
            if not service.exists():
                return {'success': False, 'error': 'Service non trouvé'}
            
            if not service.is_open:
                return {'success': False, 'error': 'Service fermé'}
            
            # Préparer les données avec validation
            ticket_data = {'service_id': service.id}
            
            if customer_phone and customer_phone.strip():
                ticket_data['customer_phone'] = customer_phone.strip()[:20]
            if customer_email and customer_email.strip():
                ticket_data['customer_email'] = customer_email.strip()[:100]
            if customer_name and customer_name.strip():
                ticket_data['customer_name'] = customer_name.strip()[:50]
            
            # Créer le ticket
            ticket = request.env['queue.ticket'].sudo().create(ticket_data)
            
            # Calculer la position
            position = len(service.waiting_ticket_ids.filtered(
                lambda t: t.ticket_number < ticket.ticket_number
            )) + 1
            
            return {
                'success': True,
                'ticket_number': ticket.ticket_number,
                'estimated_wait': ticket.estimated_wait_time or 0,
                'position': position,
                'service_name': service.name
            }
            
        except Exception as e:
            _logger.error(f"Erreur prise ticket JSON: {e}")
            return {'success': False, 'error': 'Erreur lors de la génération du ticket'}

    @http.route('/queue/status/<int:service_id>', type='json', auth='public', csrf=False)
    def queue_status(self, service_id, **kwargs):
        """Statut temps réel d'une file d'attente"""
        try:
            service = request.env['queue.service'].sudo().browse(service_id)
            if not service.exists():
                return {'error': 'Service non trouvé'}
            
            # Récupération sécurisée des tickets
            try:
                waiting_tickets = service.waiting_ticket_ids.sorted('ticket_number')[:10]
            except Exception:
                waiting_tickets = request.env['queue.ticket'].sudo().search([
                    ('service_id', '=', service.id),
                    ('state', '=', 'waiting')
                ], limit=10, order='ticket_number')
            
            return {
                'service_name': service.name,
                'waiting_count': len(waiting_tickets),
                'current_ticket': service.current_ticket_number or 0,
                'is_open': service.is_open,
                'tickets': [{
                    'number': t.ticket_number,
                    'estimated_wait': t.estimated_wait_time or 0
                } for t in waiting_tickets]
            }
            
        except Exception as e:
            _logger.error(f"Erreur statut service {service_id}: {e}")
            return {'error': 'Erreur lors de la récupération du statut'}

    @http.route('/queue/admin', type='http', auth='user', website=True)
    def admin_dashboard(self, **kwargs):
        """Interface d'administration"""
        try:
            # Vérification des permissions
            if not request.env.user.has_group('base.group_user'):
                return request.render('website.403')
            
            services = request.env['queue.service'].search([('active', '=', True)])
            
            # Force le recalcul des stats pour l'admin
            for service in services:
                try:
                    service.invalidate_cache(['waiting_count', 'avg_waiting_time', 'total_tickets_today'])
                except Exception as e:
                    _logger.warning(f"Erreur invalidation cache service {service.id}: {e}")
            
            return request.render('queue_management.admin_dashboard_template', {
                'services': services
            })
            
        except Exception as e:
            _logger.error(f"Erreur dashboard admin: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors du chargement du tableau de bord'
            })

    @http.route('/queue/health', type='json', auth='public', csrf=False)
    def health_check(self, **kwargs):
        """Vérification de santé du système"""
        try:
            # Test basique des modèles
            services_count = request.env['queue.service'].sudo().search_count([])
            tickets_count = request.env['queue.ticket'].sudo().search_count([])
            
            return {
                'success': True,
                'status': 'healthy',
                'services_count': services_count,
                'tickets_count': tickets_count,
                'database_responsive': True,
                'timestamp': fields.Datetime.now().isoformat()
            }
            
        except Exception as e:
            _logger.error(f"Health check failed: {e}")
            return {
                'success': False,
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': fields.Datetime.now().isoformat()
            }

    # Route simplifiée pour les tests
    @http.route('/queue/test', type='http', auth='public', website=True)
    def test_basic_functionality(self, **kwargs):
        """Page de test basique pour vérifier le bon fonctionnement"""
        try:
            # Test simple sans dépendances complexes
            services = request.env['queue.service'].sudo().search([('active', '=', True)], limit=5)
            
            html_content = """
            <div class="container mt-4">
                <h1>Test Queue Management</h1>
                <div class="alert alert-success">
                    <h4>✅ Système fonctionnel!</h4>
                    <p>Services trouvés: %d</p>
                </div>
                <ul class="list-group">
            """ % len(services)
            
            for service in services:
                html_content += f"""
                    <li class="list-group-item d-flex justify-content-between">
                        <span>{service.name}</span>
                        <span class="badge bg-{'success' if service.is_open else 'danger'}">
                            {'Ouvert' if service.is_open else 'Fermé'}
                        </span>
                    </li>
                """
            
            html_content += """
                </ul>
                <div class="mt-3">
                    <a href="/queue" class="btn btn-primary">Aller à la page principale</a>
                </div>
            </div>
            """
            
            return request.make_response(
                html_content,
                headers={'Content-Type': 'text/html; charset=utf-8'}
            )
            
        except Exception as e:
            _logger.error(f"Test page error: {e}")
            error_html = f"""
            <div class="container mt-4">
                <div class="alert alert-danger">
                    <h4>❌ Erreur système</h4>
                    <p>Erreur: {str(e)}</p>
                    <p>Vérifiez les logs Odoo pour plus de détails.</p>
                </div>
            </div>
            """
            return request.make_response(
                error_html,
                headers={'Content-Type': 'text/html; charset=utf-8'}
            )

    # ROUTES D'ADMINISTRATION AVANCÉES
    @http.route('/queue/admin/action', type='json', auth='user', methods=['POST'], csrf=False)
    def admin_action(self, action, ticket_id=None, service_id=None, **kwargs):
        """Actions d'administration via AJAX"""
        try:
            # Vérification des permissions
            if not request.env.user.has_group('base.group_user'):
                return {'success': False, 'error': 'Accès non autorisé'}
            
            if action == 'call_next':
                if ticket_id:
                    try:
                        ticket = request.env['queue.ticket'].browse(int(ticket_id))
                        if ticket.exists() and ticket.state == 'waiting':
                            ticket.action_call_next()
                            return {'success': True, 'message': f'Ticket #{ticket.ticket_number} appelé'}
                        else:
                            return {'success': False, 'error': 'Ticket non trouvé ou non en attente'}
                    except Exception as e:
                        _logger.error(f"Erreur appel ticket {ticket_id}: {e}")
                        return {'success': False, 'error': 'Erreur lors de l\'appel du ticket'}
                
                elif service_id:
                    try:
                        service = request.env['queue.service'].browse(int(service_id))
                        if not service.exists():
                            return {'success': False, 'error': 'Service non trouvé'}
                        
                        # Trouver le prochain ticket en attente
                        next_ticket = request.env['queue.ticket'].search([
                            ('service_id', '=', service.id),
                            ('state', '=', 'waiting')
                        ], order='ticket_number', limit=1)
                        
                        if next_ticket:
                            next_ticket.action_call_next()
                            return {'success': True, 'message': f'Ticket #{next_ticket.ticket_number} appelé'}
                        else:
                            return {'success': False, 'error': 'Aucun ticket en attente'}
                    except Exception as e:
                        _logger.error(f"Erreur appel suivant service {service_id}: {e}")
                        return {'success': False, 'error': 'Erreur lors de l\'appel du ticket suivant'}
            
            elif action == 'generate_ticket' and service_id:
                try:
                    service = request.env['queue.service'].browse(int(service_id))
                    if not service.exists():
                        return {'success': False, 'error': 'Service non trouvé'}
                    
                    if not service.is_open:
                        return {'success': False, 'error': 'Service fermé'}
                    
                    # Créer un ticket manuel
                    ticket = request.env['queue.ticket'].create({
                        'service_id': service.id,
                        'customer_name': 'Ticket manuel'
                    })
                    return {'success': True, 'message': f'Ticket #{ticket.ticket_number} généré'}
                    
                except Exception as e:
                    _logger.error(f"Erreur génération ticket service {service_id}: {e}")
                    return {'success': False, 'error': 'Erreur lors de la génération du ticket'}
            
            elif action == 'toggle_service' and service_id:
                try:
                    service = request.env['queue.service'].browse(int(service_id))
                    if not service.exists():
                        return {'success': False, 'error': 'Service non trouvé'}
                    
                    service.is_open = not service.is_open
                    status = "ouvert" if service.is_open else "fermé"
                    return {'success': True, 'message': f'Service {status}'}
                    
                except Exception as e:
                    _logger.error(f"Erreur toggle service {service_id}: {e}")
                    return {'success': False, 'error': 'Erreur lors du changement de statut'}
            
            elif action == 'complete_service' and ticket_id:
                try:
                    ticket = request.env['queue.ticket'].browse(int(ticket_id))
                    if ticket.exists() and ticket.state in ['called', 'serving']:
                        ticket.action_complete_service()
                        return {'success': True, 'message': f'Service ticket #{ticket.ticket_number} terminé'}
                    else:
                        return {'success': False, 'error': 'Ticket non trouvé ou non en service'}
                except Exception as e:
                    _logger.error(f"Erreur fin service ticket {ticket_id}: {e}")
                    return {'success': False, 'error': 'Erreur lors de la finalisation du service'}
            
            else:
                return {'success': False, 'error': 'Action non reconnue ou paramètres manquants'}
                
        except Exception as e:
            _logger.error(f"Erreur générale admin_action: {e}")
            return {'success': False, 'error': 'Erreur système'}

    # ROUTES D'ANNULATION DE TICKETS
    @http.route('/queue/cancel_ticket', type='json', auth='public', methods=['POST'], csrf=False)
    def cancel_ticket(self, ticket_number, service_id, reason='', **kwargs):
        """Annuler un ticket - VERSION ULTRA-SÉCURISÉE"""
        try:
            # Validation stricte
            if not ticket_number or not service_id:
                return {'success': False, 'error': 'Paramètres manquants'}
            
            try:
                ticket_number = int(ticket_number)
                service_id = int(service_id)
            except (ValueError, TypeError):
                return {'success': False, 'error': 'Paramètres invalides'}
            
            # Recherche sécurisée du ticket
            ticket = request.env['queue.ticket'].sudo().search([
                ('ticket_number', '=', ticket_number),
                ('service_id', '=', service_id),
                ('state', 'in', ['waiting', 'called'])
            ], limit=1)
            
            if not ticket:
                return {'success': False, 'error': 'Ticket non trouvé ou déjà traité'}
            
            # Annulation sécurisée
            try:
                cancel_reason = f"Annulé par le client: {reason.strip()}" if reason else "Annulé par le client"
                
                ticket.sudo().write({
                    'state': 'cancelled',
                    'completed_time': fields.Datetime.now(),
                    'notes': cancel_reason
                })
                
                _logger.info(f"Ticket #{ticket.ticket_number} annulé par le client")
                
                return {
                    'success': True,
                    'message': f'Ticket #{ticket.ticket_number} annulé avec succès'
                }
                
            except Exception as e:
                _logger.error(f"Erreur lors de l'annulation: {e}")
                return {'success': False, 'error': 'Erreur lors de l\'annulation'}
            
        except Exception as e:
            _logger.error(f"Erreur générale annulation: {e}")
            return {'success': False, 'error': 'Erreur système'}

    @http.route('/queue/ticket_position', type='json', auth='public', methods=['POST'], csrf=False)
    def get_ticket_position(self, ticket_number, service_id, **kwargs):
        """Obtenir la position actuelle d'un ticket dans la file"""
        try:
            if not ticket_number or not service_id:
                return {'success': False, 'error': 'Paramètres manquants'}
            
            # Trouver le ticket
            ticket = request.env['queue.ticket'].sudo().search([
                ('ticket_number', '=', int(ticket_number)),
                ('service_id', '=', int(service_id))
            ], limit=1)
            
            if not ticket:
                return {'success': False, 'error': 'Ticket non trouvé'}
            
            if ticket.state != 'waiting':
                return {'success': True, 'position': 0, 'state': ticket.state}
            
            # Calculer la position
            tickets_before_count = request.env['queue.ticket'].sudo().search_count([
                ('service_id', '=', ticket.service_id.id),
                ('state', '=', 'waiting'),
                ('ticket_number', '<', ticket.ticket_number)
            ])
            position = tickets_before_count + 1
            
            # Recalculer le temps d'attente estimé
            avg_service_time = ticket.service_id.avg_service_time or 5
            estimated_wait = position * avg_service_time
            
            return {
                'success': True,
                'position': position,
                'estimated_wait': estimated_wait,
                'state': ticket.state,
                'current_ticket': ticket.service_id.current_ticket_number
            }
            
        except ValueError as e:
            _logger.error(f"Erreur de validation pour position ticket: {str(e)}")
            return {'success': False, 'error': 'Données invalides'}
        except Exception as e:
            _logger.error(f"Erreur lors du calcul de position: {str(e)}")
            return {'success': False, 'error': 'Erreur serveur'}

    # ROUTES DE DEBUGGING ET DIAGNOSTICS
    @http.route('/queue/debug/stats', type='json', auth='user', methods=['GET'], csrf=False)
    def debug_statistics(self, **kwargs):
        """Route de debug pour analyser les problèmes de statistiques"""
        if not request.env.user.has_group('queue_management.group_queue_user'):
            return {'error': 'Accès non autorisé'}
        
        try:
            services = request.env['queue.service'].search([('active', '=', True)])
            debug_data = {}
            
            for service in services:
                # Forcer le recalcul
                service.force_refresh_stats()
                
                today_tickets = service.ticket_ids.filtered(
                    lambda t: t.created_time and t.created_time.date() == fields.Date.today()
                )
                
                debug_data[service.name] = {
                    'service_id': service.id,
                    'total_tickets_today': len(today_tickets),
                    'avg_waiting_time': service.avg_waiting_time,
                    'waiting_count': service.waiting_count,
                    'tickets_details': [
                        {
                            'number': t.ticket_number,
                            'state': t.state,
                            'waiting_time': t.waiting_time,
                            'created_time': t.created_time.isoformat() if t.created_time else None,
                            'called_time': t.called_time.isoformat() if t.called_time else None,
                        }
                        for t in today_tickets[:3]
                    ]
                }
            
            return {
                'success': True,
                'debug_data': debug_data,
                'timestamp': fields.Datetime.now().isoformat()
            }
            
        except Exception as e:
            _logger.error(f"Erreur debug statistiques: {e}")
            return {'success': False, 'error': str(e)}

    @http.route('/queue/force_refresh', type='json', auth='user', methods=['POST'], csrf=False)
    def force_refresh_statistics(self, **kwargs):
        """Force le rafraîchissement des statistiques"""
        if not request.env.user.has_group('queue_management.group_queue_user'):
            return {'error': 'Accès non autorisé'}
        
        try:
            services = request.env['queue.service'].search([('active', '=', True)])
            
            # Forcer le recalcul pour tous les services
            for service in services:
                service.force_refresh_stats()
            
            # Récupérer les nouvelles données
            dashboard_data = request.env['queue.service'].get_dashboard_data()
            
            return {
                'success': True,
                'message': f'{len(services)} services mis à jour',
                'data': dashboard_data
            }
            
        except Exception as e:
            _logger.error(f"Erreur refresh forcé: {e}")
            return {'success': False, 'error': str(e)}

    # ROUTES D'URGENCE ET RESET
    @http.route('/queue/emergency_reset', type='http', auth='user', methods=['GET', 'POST'])
    def emergency_reset(self, **kwargs):
        """Reset d'urgence pour débloquer le système"""
        try:
            if not request.env.user.has_group('base.group_system'):
                return "Accès admin requis"
            
            if request.httprequest.method == 'POST':
                # Effectuer le reset
                request.env.cr.rollback()
                
                # Nettoyer les données problématiques
                request.env['queue.ticket'].sudo().search([
                    ('state', 'not in', ['waiting', 'called', 'serving', 'served', 'cancelled', 'no_show'])
                ]).unlink()
                
                # Reset les services
                services = request.env['queue.service'].sudo().search([])
                for service in services:
                    service.invalidate_cache()
                
                request.env.cr.commit()
                
                return """
                <div class="container mt-4">
                    <div class="alert alert-success">
                        <h4>✅ Reset d'urgence effectué!</h4>
                        <p>Le système a été nettoyé et réinitialisé.</p>
                        <a href="/queue" class="btn btn-primary">Tester le système</a>
                    </div>
                </div>
                """
            
            return """
            <div class="container mt-4">
                <div class="alert alert-warning">
                    <h4>⚠️ Reset d'urgence du système</h4>
                    <p>Cette action va nettoyer les données corrompues et réinitialiser les transactions.</p>
                    <form method="post">
                        <button type="submit" class="btn btn-danger">Confirmer le reset</button>
                        <a href="/queue" class="btn btn-secondary">Annuler</a>
                    </form>
                </div>
            </div>
            """
            
        except Exception as e:
            _logger.error(f"Erreur reset urgence: {e}")
            return f"<h1>Erreur reset: {str(e)}</h1>"

    @http.route('/queue/debug/reset', type='json', auth='user', methods=['POST'], csrf=False)
    def debug_reset_system(self, confirm=False, **kwargs):
        """Reset complet du système pour debug - ADMIN SEULEMENT"""
        try:
            # Vérification admin stricte
            if not request.env.user.has_group('base.group_system'):
                return {'success': False, 'error': 'Accès admin requis'}
            
            if not confirm:
                return {
                    'success': False, 
                    'error': 'Confirmation requise',
                    'message': 'Ajoutez "confirm": true pour confirmer la réinitialisation'
                }
            
            # Reset du système
            request.env.cr.rollback()  # Nettoyer toute transaction échouée
            
            # Supprimer tous les tickets
            tickets = request.env['queue.ticket'].sudo().search([])
            tickets.unlink()
            
            # Reset des compteurs de services
            services = request.env['queue.service'].sudo().search([])
            for service in services:
                service.sudo().write({
                    'current_ticket_number': 0,
                    'next_ticket_number': 1,
                })
                # Force recalcul
                service.invalidate_cache()
            
            request.env.cr.commit()
            
            return {
                'success': True,
                'message': f'Système réinitialisé: {len(tickets)} tickets supprimés, {len(services)} services reset'
            }
            
        except Exception as e:
            _logger.error(f"Erreur reset système: {e}")
            request.env.cr.rollback()
            return {'success': False, 'error': f'Erreur reset: {str(e)}'}

    # ROUTES DE FEEDBACK
    @http.route('/queue/feedback/<int:ticket_id>', type='http', auth='public', website=True, methods=['GET', 'POST'])
    def ticket_feedback(self, ticket_id, **kwargs):
        """Page de feedback pour un ticket"""
        ticket = request.env['queue.ticket'].sudo().browse(ticket_id)
        if not ticket.exists() or ticket.state != 'served':
            return request.render('queue_management.error_template', {
                'error_message': 'Ticket non trouvé ou non éligible pour un feedback'
            })
        
        if request.httprequest.method == 'POST':
            # Traitement du feedback
            rating = kwargs.get('rating')
            feedback = kwargs.get('feedback', '')
            
            if rating:
                ticket.write({
                    'rating': rating,
                    'feedback': feedback
                })
                return request.render('queue_management.feedback_thanks_template', {
                    'ticket': ticket,
                    'service': ticket.service_id
                })
        
        return request.render('queue_management.feedback_form_template', {
            'ticket': ticket,
            'service': ticket.service_id
        })