# controllers/main.py - VERSION MISE À JOUR AVEC RÉFÉRENCES UNIQUES
from odoo import http, fields
from odoo.http import request
from datetime import datetime
import json
import logging
import hashlib

_logger = logging.getLogger(__name__)

class QueueDashboardController(http.Controller):
    @http.route('/queue_dashboard', type='json', auth='user')
    def get_dashboard_data(self, **kwargs):
        # Your data fetching logic here
        return {
            'services': [],
            'waiting_tickets': [],
            'serving_tickets': [],
            'stats': {},
            'last_update': fields.Datetime.now()
        }

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

    # ========================================
    # ROUTES D'IMPRESSION AMÉLIORÉES AVEC RÉFÉRENCES
    # ========================================
    
    @http.route([
        '/queue/print_ticket/<int:ticket_number>/<int:service_id>',
        '/queue/print/<reference>'
    ], type='http', auth='public', website=False, csrf=False)
    def print_ticket(self, ticket_number=None, service_id=None, reference=None, auto_print=None, auto_close=None, **kwargs):
        """Version imprimable du ticket - ROUTE PRINCIPALE avec références"""
        try:
            ticket = None
            
            # Méthode 1: Par référence unique (nouvelle)
            if reference:
                _logger.info(f"Impression ticket par référence: {reference}")
                ticket = request.env['queue.ticket'].sudo().find_ticket_by_reference(reference)
                if not ticket:
                    # Essayer avec référence courte
                    ticket = request.env['queue.ticket'].sudo().find_ticket_by_reference(reference, 'short')
            
            # Méthode 2: Par numéro + service (legacy)
            elif ticket_number and service_id:
                _logger.info(f"Impression ticket #{ticket_number} pour service {service_id}")
                ticket = request.env['queue.ticket'].sudo().search([
                    ('ticket_number', '=', ticket_number),
                    ('service_id', '=', service_id)
                ], limit=1)
            
            if not ticket:
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
                        <p>Référence: {reference or f"#{ticket_number}/{service_id}"} introuvable.</p>
                        <button onclick="window.close()">Fermer</button>
                    </div>
                </body>
                </html>
                """
                return request.make_response(error_html, headers={'Content-Type': 'text/html; charset=utf-8'})
            
            service = ticket.service_id
            
            # Calculer la position
            position = ticket.get_queue_position() if hasattr(ticket, 'get_queue_position') else 1
            
            # URL de tracking améliorée (avec référence unique)
            track_url = f"{request.httprequest.host_url}queue/track/{ticket.ticket_reference}" if hasattr(ticket, 'ticket_reference') and ticket.ticket_reference else f"{request.httprequest.host_url}queue/my_ticket/{ticket.ticket_number}/{service.id}"
            
            # Template d'impression optimisé avec références
            print_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Ticket {ticket.ticket_reference or f'#{ticket.ticket_number}'}</title>
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
                        font-size: 20px;
                        font-weight: bold;
                        margin: 8px 0;
                    }}
                    .reference {{
                        font-size: 16px;
                        font-weight: bold;
                        margin: 5px 0;
                        color: #333;
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
                    {f'<div class="reference">{ticket.ticket_reference}</div>' if hasattr(ticket, 'ticket_reference') and ticket.ticket_reference else ''}
                    {f'<div class="reference">Code: {ticket.short_reference}</div>' if hasattr(ticket, 'short_reference') and ticket.short_reference else ''}
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
                    <img src="https://api.qrserver.com/v1/create-qr-code/?size=100x100&data={track_url}" 
                         alt="QR Code" style="width: 60px; height: 60px;">
                </div>
                
                <div class="footer">
                    <div>Présentez-vous quand</div>
                    <div>votre numéro sera appelé</div>
                    <div style="margin-top: 5px;">
                        Suivi: {request.httprequest.host_url.replace('http://', '').replace('https://', '').split('/')[0]}
                    </div>
                    {f"<div style='font-size: 9px; margin-top: 3px;'>Ref: {ticket.short_reference}</div>" if hasattr(ticket, 'short_reference') and ticket.short_reference else ""}
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

    # ========================================
    # NOUVELLES ROUTES AVEC RÉFÉRENCES UNIQUES
    # ========================================
    
    @http.route('/queue/track/<reference>', type='http', auth='public', website=True)
    def track_ticket_by_reference(self, reference, **kwargs):
        """Suivi de ticket par référence unique (principale ou courte)"""
        try:
            # Utiliser la nouvelle méthode de recherche
            result = request.env['queue.ticket'].sudo().get_ticket_by_reference_web(reference)
            
            if not result['success']:
                return request.render('queue_management.ticket_not_found_template', {
                    'reference': reference,
                    'error_message': result.get('error', 'Ticket non trouvé')
                })
            
            ticket_data = result['ticket']
            ticket = request.env['queue.ticket'].sudo().browse(ticket_data['id'])
            
            return request.render('queue_management.my_ticket_template', {
                'ticket': ticket,
                'service': ticket.service_id,
                'position': ticket_data['position'],
                'reference': reference,
                'can_cancel': ticket_data['can_cancel'],
                'security_hash': ticket_data.get('security_hash', '')
            })
            
        except Exception as e:
            _logger.error(f"Erreur suivi par référence {reference}: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors du chargement des informations du ticket'
            })

    # Méthode d'annulation corrigée dans le contrôleur
    @http.route('/queue/cancel/<reference>', type='http', auth='public', website=True, methods=['GET', 'POST'], csrf=False)
    def cancel_ticket_by_reference(self, reference, **kwargs):
        """Annulation de ticket par référence unique - VERSION CORRIGÉE"""
        try:
            if request.httprequest.method == 'GET':
                # Afficher le formulaire d'annulation
                ticket = request.env['queue.ticket'].sudo().find_ticket_by_reference(reference)
                
                if not ticket:
                    # Essayer avec référence courte
                    ticket = request.env['queue.ticket'].sudo().find_ticket_by_reference(reference, 'short')
                
                if not ticket:
                    return request.render('queue_management.ticket_not_found_template', {
                        'reference': reference,
                        'error_message': f'Ticket avec référence {reference} non trouvé'
                    })
                
                # Vérifier l'état du ticket
                if ticket.state not in ['waiting', 'called']:
                    state_labels = {
                        'served': 'déjà servi',
                        'cancelled': 'déjà annulé',
                        'no_show': 'marqué comme absent'
                    }
                    return request.render('queue_management.error_template', {
                        'error_message': f'Ce ticket est {state_labels.get(ticket.state, "dans un état non annulable")}'
                    })
                
                # Récupérer le hash de sécurité
                security_hash = getattr(ticket, 'security_hash', '') if hasattr(ticket, 'security_hash') else ''
                
                return request.render('queue_management.cancel_ticket_template', {
                    'ticket': ticket,
                    'reference': reference,
                    'security_hash': security_hash
                })
            
            elif request.httprequest.method == 'POST':
                # Traiter l'annulation
                reason = kwargs.get('reason', '').strip()[:500]  # Limiter la longueur
                security_hash = kwargs.get('security_hash', '')
                ticket_id = kwargs.get('ticket_id')
                
                _logger.info(f"Tentative d'annulation pour référence {reference}")
                
                # Retrouver le ticket
                ticket = request.env['queue.ticket'].sudo().find_ticket_by_reference(reference)
                if not ticket:
                    ticket = request.env['queue.ticket'].sudo().find_ticket_by_reference(reference, 'short')
                
                # Vérification par ID si la référence échoue
                if not ticket and ticket_id:
                    try:
                        ticket = request.env['queue.ticket'].sudo().browse(int(ticket_id))
                        if not ticket.exists():
                            ticket = None
                    except (ValueError, TypeError):
                        ticket = None
                
                if not ticket:
                    return request.render('queue_management.error_template', {
                        'error_message': f'Ticket avec référence {reference} non trouvé'
                    })
                
                # Vérification de l'état avant annulation
                if ticket.state not in ['waiting', 'called']:
                    return request.render('queue_management.error_template', {
                        'error_message': f'Ce ticket ne peut plus être annulé (état: {ticket.state})'
                    })
                
                # Vérifier le hash de sécurité si présent
                if hasattr(ticket, 'security_hash') and ticket.security_hash:
                    if security_hash != ticket.security_hash:
                        _logger.warning(f"Hash de sécurité invalide pour ticket {ticket.id}")
                        return request.render('queue_management.error_template', {
                            'error_message': 'Code de sécurité invalide'
                        })
                
                try:
                    # Effectuer l'annulation
                    old_state = ticket.state
                    ticket.write({
                        'state': 'cancelled',
                        'cancelled_time': fields.Datetime.now(),
                        'cancellation_reason': reason
                    })
                    
                    _logger.info(f"Ticket {ticket.id} (ref: {reference}) annulé avec succès - état précédent: {old_state}")
                    
                    # Message de succès
                    success_message = f"Votre ticket #{ticket.ticket_number} pour le service '{ticket.service_id.name}' a été annulé."
                    if reason:
                        success_message += f" Raison : {reason}"
                    
                    return request.render('queue_management.cancellation_success_template', {
                        'message': success_message,
                        'reference': reference,
                        'ticket': ticket
                    })
                    
                except Exception as cancel_error:
                    _logger.error(f"Erreur lors de l'annulation du ticket {ticket.id}: {cancel_error}")
                    return request.render('queue_management.error_template', {
                        'error_message': 'Une erreur est survenue lors de l\'annulation. Veuillez réessayer.'
                    })
                    
        except Exception as e:
            _logger.error(f"Erreur annulation par référence {reference}: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur technique lors de l\'annulation'
            })





    # Route alternative pour annulation par numéro/service (legacy)
    @http.route('/queue/cancel_legacy/<int:ticket_number>/<int:service_id>', 
                type='http', auth='public', website=True, methods=['GET', 'POST'], csrf=False)
    def cancel_ticket_legacy(self, ticket_number, service_id, **kwargs):
        """Annulation de ticket par numéro/service (compatibilité)"""
        try:
            ticket = request.env['queue.ticket'].sudo().search([
                ('ticket_number', '=', ticket_number),
                ('service_id', '=', service_id)
            ], limit=1)
            
            if not ticket:
                return request.render('queue_management.error_template', {
                    'error_message': f'Ticket #{ticket_number} non trouvé pour ce service'
                })
            
            # Si le ticket a une référence, rediriger vers la nouvelle route
            if hasattr(ticket, 'ticket_reference') and ticket.ticket_reference:
                return request.redirect(f'/queue/cancel/{ticket.ticket_reference}')
            
            # Sinon, traiter ici (même logique que ci-dessus)
            if request.httprequest.method == 'GET':
                if ticket.state not in ['waiting', 'called']:
                    return request.render('queue_management.error_template', {
                        'error_message': 'Ce ticket ne peut plus être annulé'
                    })
                
                return request.render('queue_management.cancel_ticket_template', {
                    'ticket': ticket,
                    'reference': f"{ticket_number}/{service_id}",
                    'security_hash': getattr(ticket, 'security_hash', '')
                })
            
            elif request.httprequest.method == 'POST':
                reason = kwargs.get('reason', '').strip()[:500]
                
                if ticket.state not in ['waiting', 'called']:
                    return request.render('queue_management.error_template', {
                        'error_message': 'Ce ticket ne peut plus être annulé'
                    })
                
                try:
                    ticket.write({
                        'state': 'cancelled',
                        'cancelled_time': fields.Datetime.now(),
                        'cancellation_reason': reason
                    })
                    
                    success_message = f"Ticket #{ticket_number} annulé avec succès."
                    
                    return request.render('queue_management.cancellation_success_template', {
                        'message': success_message,
                        'reference': f"{ticket_number}/{service_id}",
                        'ticket': ticket
                    })
                    
                except Exception as e:
                    _logger.error(f"Erreur annulation legacy {ticket_number}/{service_id}: {e}")
                    return request.render('queue_management.error_template', {
                        'error_message': 'Erreur lors de l\'annulation'
                    })
                    
        except Exception as e:
            _logger.error(f"Erreur cancel_ticket_legacy: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur technique'
            })

    # Méthode utilitaire pour valider l'annulation
    def _can_cancel_ticket(self, ticket):
        """Vérifier si un ticket peut être annulé"""
        if not ticket or not ticket.exists():
            return False, "Ticket non trouvé"
        
        if ticket.state not in ['waiting', 'called']:
            state_messages = {
                'served': 'Le ticket a déjà été servi',
                'cancelled': 'Le ticket a déjà été annulé',
                'no_show': 'Le ticket a été marqué comme absent'
            }
            return False, state_messages.get(ticket.state, f'État non annulable: {ticket.state}')
        
        return True, ""

    # ========================================
    # ROUTES PRINCIPALES MISES À JOUR
    # ========================================
    
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
    
    @http.route('/queue/take_ticket_http', type='http', auth='public', methods=['POST'], csrf=False, website=True)
    def take_ticket_http(self, service_id, customer_phone='', customer_email='', customer_name='', **kwargs):
        """Prendre un ticket via formulaire HTTP - VERSION AVEC RÉFÉRENCES"""

        def create_error_response(message, service=None):
            """Créer une réponse d'erreur sans dépendre des templates"""
            try:
                context = {'error_message': message}
                if service:
                    context['service'] = service
                return request.render('queue_management.error_template', context)
            except Exception as template_error:
                _logger.error(f"Template error_template échoué: {template_error}")
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
            
            # Créer le ticket (les références sont générées automatiquement)
            ticket = request.env['queue.ticket'].sudo().create(ticket_data)
            
            if not ticket or not ticket.exists():
                return create_error_response('Impossible de créer le ticket')
            
            _logger.info(f"Ticket {ticket.ticket_reference or f'#{ticket.ticket_number}'} créé avec succès pour service {service.name}")
            
            # Redirection vers confirmation avec référence
            if hasattr(ticket, 'ticket_reference') and ticket.ticket_reference:
                return request.redirect(f'/queue/confirmation/{ticket.ticket_reference}')
            else:
                return request.redirect(f'/queue/ticket_confirmation/{ticket.id}')
            
        except Exception as e:
            _logger.error(f"Erreur création ticket: {e}")
            return create_error_response('Une erreur est survenue lors de la création du ticket')

    @http.route([
        '/queue/confirmation/<reference>',
        '/queue/ticket_confirmation/<int:ticket_id>'
    ], type='http', auth='public', website=True)
    def ticket_confirmation(self, reference=None, ticket_id=None, **kwargs):
        """Page de confirmation après création d'un ticket"""
        try:
            ticket = None
            
            # Méthode 1: Par référence (nouvelle)
            if reference:
                ticket = request.env['queue.ticket'].sudo().find_ticket_by_reference(reference)
            
            # Méthode 2: Par ID (legacy)
            elif ticket_id:
                ticket = request.env['queue.ticket'].sudo().browse(ticket_id)
            
            if not ticket or not ticket.exists():
                return request.render('queue_management.error_template', {
                    'error_message': 'Ticket non trouvé'
                })
            
            # Calculer la position de manière sécurisée
            position = ticket.get_queue_position() if hasattr(ticket, 'get_queue_position') else 1
            
            # URL de tracking avec référence
            if hasattr(ticket, 'ticket_reference') and ticket.ticket_reference:
                track_url = f'/queue/track/{ticket.ticket_reference}'
                print_url = f'/queue/print/{ticket.ticket_reference}'
            else:
                track_url = f'/queue/my_ticket/{ticket.ticket_number}/{ticket.service_id.id}'
                print_url = f'/queue/print_ticket/{ticket.ticket_number}/{ticket.service_id.id}'
            
            return request.render('queue_management.ticket_confirmation_template', {
                'ticket': ticket,
                'service': ticket.service_id,
                'position': position,
                'track_url': track_url,
                'print_url': print_url,
                'reference': getattr(ticket, 'ticket_reference', None),
                'short_reference': getattr(ticket, 'short_reference', None)
            })
            
        except Exception as e:
            _logger.error(f"Erreur confirmation ticket: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors de l\'affichage de la confirmation'
            })

    # ========================================
    # API JSON ENDPOINTS AMÉLIORÉS
    # ========================================
    
    @http.route('/queue/take_ticket', type='json', auth='public', methods=['POST'], csrf=False)
    def take_ticket_json(self, service_id, customer_phone='', customer_email='', customer_name='', **kwargs):
        """Prendre un ticket via API JSON - VERSION AVEC RÉFÉRENCES"""
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
            
            # Créer le ticket (références générées automatiquement)
            ticket = request.env['queue.ticket'].sudo().create(ticket_data)
            
            # Calculer la position
            position = ticket.get_queue_position() if hasattr(ticket, 'get_queue_position') else 1
            
            # Préparer la réponse avec références
            response = {
                'success': True,
                'ticket_number': ticket.ticket_number,
                'estimated_wait': ticket.estimated_wait_time or 0,
                'position': position,
                'service_name': service.name,
                'ticket_id': ticket.id
            }
            
            # Ajouter les références si disponibles
            if hasattr(ticket, 'ticket_reference') and ticket.ticket_reference:
                response['ticket_reference'] = ticket.ticket_reference
                response['track_url'] = f'/queue/track/{ticket.ticket_reference}'
                response['print_url'] = f'/queue/print/{ticket.ticket_reference}'
            
            if hasattr(ticket, 'short_reference') and ticket.short_reference:
                response['short_reference'] = ticket.short_reference
            
            if hasattr(ticket, 'security_hash') and ticket.security_hash:
                response['security_hash'] = ticket.security_hash
            
            return response
            
        except Exception as e:
            _logger.error(f"Erreur prise ticket JSON: {e}")
            return {'success': False, 'error': 'Erreur lors de la génération du ticket'}

    @http.route('/queue/ticket_info', type='json', auth='public', methods=['POST'], csrf=False)
    def get_ticket_info(self, reference=None, ticket_number=None, service_id=None, **kwargs):
        """Obtenir les informations d'un ticket par référence ou numéro"""
        try:
            ticket = None
            
            # Méthode 1: Par référence unique
            if reference:
                result = request.env['queue.ticket'].sudo().get_ticket_by_reference_web(reference)
                return result
            
            # Méthode 2: Par numéro + service (legacy)
            elif ticket_number and service_id:
                try:
                    ticket_number = int(ticket_number)
                    service_id = int(service_id)
                except (ValueError, TypeError):
                    return {'success': False, 'error': 'Paramètres invalides'}
                
                result = request.env['queue.ticket'].sudo().get_ticket_status_web(ticket_number, service_id)
                return result
            
            else:
                return {'success': False, 'error': 'Référence ou numéro de ticket requis'}
                
        except Exception as e:
            _logger.error(f"Erreur get_ticket_info: {e}")
            return {'success': False, 'error': 'Erreur lors de la récupération des informations'}

    @http.route('/queue/cancel_ticket', type='json', auth='public', methods=['POST'], csrf=False)
    def cancel_ticket(self, reference=None, ticket_number=None, service_id=None, reason='', security_hash=None, **kwargs):
        """Annuler un ticket - VERSION AVEC RÉFÉRENCES"""
        try:
            # Méthode 1: Par référence unique (nouvelle)
            if reference:
                result = request.env['queue.ticket'].sudo().cancel_ticket_by_reference_web(
                    reference, reason, security_hash
                )
                return result
            
            # Méthode 2: Par numéro + service (legacy)
            elif ticket_number and service_id:
                try:
                    ticket_number = int(ticket_number)
                    service_id = int(service_id)
                except (ValueError, TypeError):
                    return {'success': False, 'error': 'Paramètres invalides'}
                
                # Utiliser l'ancienne méthode
                data = {
                    'ticket_number': ticket_number,
                    'service_id': service_id,
                    'reason': reason
                }
                
                # Essayer la nouvelle méthode d'annulation
                if hasattr(request.env['queue.ticket'], 'cancel_ticket_web_v2'):
                    result = request.env['queue.ticket'].sudo().cancel_ticket_web_v2(data)
                else:
                    result = request.env['queue.ticket'].sudo().cancel_ticket_web(data)
                
                return result
            
            else:
                return {'success': False, 'error': 'Référence ou numéro de ticket requis'}
                
        except Exception as e:
            _logger.error(f"Erreur annulation ticket: {e}")
            return {'success': False, 'error': 'Erreur lors de l\'annulation'}

    # ========================================
    # ROUTES D'ADMINISTRATION AMÉLIORÉES
    # ========================================
    
    @http.route('/queue/admin', type='http', auth='user', website=True)
    def admin_dashboard(self, **kwargs):
        """Interface d'administration avec références"""
        try:
            if not request.env.user.has_group('base.group_user'):
                return request.render('website.403')
            
            services = request.env['queue.service'].search([('active', '=', True)])
            
            # Force le recalcul des stats pour l'admin
            for service in services:
                try:
                    service.invalidate_cache(['waiting_count', 'avg_waiting_time', 'total_tickets_today'])
                except Exception as e:
                    _logger.warning(f"Erreur invalidation cache service {service.id}: {e}")
            
            # Statistiques globales avec références
            total_tickets_today = request.env['queue.ticket'].search_count([
                ('created_time', '>=', fields.Date.today())
            ])
            
            tickets_with_references = request.env['queue.ticket'].search_count([
                ('ticket_reference', '!=', False),
                ('created_time', '>=', fields.Date.today())
            ])
            
            return request.render('queue_management.admin_dashboard_template', {
                'services': services,
                'total_tickets_today': total_tickets_today,
                'tickets_with_references': tickets_with_references,
                'reference_coverage': (tickets_with_references / max(total_tickets_today, 1)) * 100
            })
            
        except Exception as e:
            _logger.error(f"Erreur dashboard admin: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors du chargement du tableau de bord'
            })

    @http.route('/queue/admin/references', type='http', auth='user', website=True)
    def admin_references(self, **kwargs):
        """Page d'administration des références"""
        try:
            if not request.env.user.has_group('base.group_user'):
                return request.render('website.403')
            
            # Statistiques des références
            stats = {
                'total_tickets': request.env['queue.ticket'].search_count([]),
                'tickets_with_main_ref': request.env['queue.ticket'].search_count([('ticket_reference', '!=', False)]),
                'tickets_with_short_ref': request.env['queue.ticket'].search_count([('short_reference', '!=', False)]),
                'tickets_with_hash': request.env['queue.ticket'].search_count([('security_hash', '!=', False)])
            }
            
            # Vérification de l'unicité
            uniqueness_check = request.env['queue.ticket'].check_reference_uniqueness()
            
            # Tickets récents avec références
            recent_tickets = request.env['queue.ticket'].search([
                ('created_time', '>=', fields.Datetime.now().replace(hour=0, minute=0, second=0))
            ], order='created_time desc', limit=10)
            
            return request.render('queue_management.admin_references_template', {
                'stats': stats,
                'uniqueness_check': uniqueness_check,
                'recent_tickets': recent_tickets
            })
            
        except Exception as e:
            _logger.error(f"Erreur admin références: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors du chargement de la page des références'
            })

    @http.route('/queue/admin/generate_references', type='json', auth='user', methods=['POST'], csrf=False)
    def admin_generate_references(self, **kwargs):
        """Générer les références manquantes pour les tickets existants"""
        try:
            if not request.env.user.has_group('base.group_user'):
                return {'success': False, 'error': 'Accès non autorisé'}
            
            # Générer les références manquantes
            count = request.env['queue.ticket'].generate_missing_references()
            
            return {
                'success': True,
                'message': f'Références générées pour {count} tickets',
                'count': count
            }
            
        except Exception as e:
            _logger.error(f"Erreur génération références: {e}")
            return {'success': False, 'error': str(e)}

    # ========================================
    # ROUTES DE RECHERCHE ET NAVIGATION
    # ========================================
    
    @http.route('/queue/search', type='http', auth='public', website=True, methods=['GET', 'POST'], csrf=False)
    def search_ticket(self, **kwargs):
        """Page de recherche de ticket par référence"""
        try:
            if request.httprequest.method == 'POST':
                search_query = kwargs.get('search_query', '').strip()
                
                if not search_query:
                    return request.render('queue_management.search_ticket_template', {
                        'error': 'Veuillez saisir une référence'
                    })
                
                # Essayer de trouver le ticket
                ticket = request.env['queue.ticket'].sudo().find_ticket_by_reference(search_query)
                
                if not ticket:
                    # Essayer avec référence courte
                    ticket = request.env['queue.ticket'].sudo().find_ticket_by_reference(search_query, 'short')
                
                if not ticket:
                    # Essayer par numéro de ticket (legacy)
                    try:
                        ticket_number = int(search_query.replace('#', ''))
                        tickets = request.env['queue.ticket'].sudo().search([
                            ('ticket_number', '=', ticket_number)
                        ])
                        if len(tickets) == 1:
                            ticket = tickets
                        elif len(tickets) > 1:
                            return request.render('queue_management.search_ticket_template', {
                                'error': f'Plusieurs tickets trouvés avec le numéro {ticket_number}. Utilisez la référence complète.',
                                'multiple_tickets': tickets
                            })
                    except ValueError:
                        pass
                
                if ticket:
                    # Rediriger vers le suivi du ticket
                    if hasattr(ticket, 'ticket_reference') and ticket.ticket_reference:
                        return request.redirect(f'/queue/track/{ticket.ticket_reference}')
                    else:
                        return request.redirect(f'/queue/my_ticket/{ticket.ticket_number}/{ticket.service_id.id}')
                else:
                    return request.render('queue_management.search_ticket_template', {
                        'error': f'Aucun ticket trouvé avec la référence "{search_query}"'
                    })
            
            # Affichage du formulaire de recherche
            return request.render('queue_management.search_ticket_template', {})
            
        except Exception as e:
            _logger.error(f"Erreur recherche ticket: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors de la recherche'
            })

    # ========================================
    # ROUTES HÉRITÉES (COMPATIBILITÉ)
    # ========================================
    
    @http.route('/queue/my_ticket/<int:ticket_number>/<int:service_id>', 
                type='http', auth='public', website=True)
    def my_ticket_status(self, ticket_number, service_id, **kwargs):
        """Page de suivi d'un ticket spécifique (legacy)"""
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
            
            # Si le ticket a une référence, rediriger vers la nouvelle route
            if hasattr(ticket, 'ticket_reference') and ticket.ticket_reference:
                return request.redirect(f'/queue/track/{ticket.ticket_reference}')
            
            # Calculer la position de manière défensive
            position = ticket.get_queue_position() if hasattr(ticket, 'get_queue_position') else 1
            
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

    # ========================================
    # ROUTES UTILITAIRES ET MAINTENANCE
    # ========================================
    
    @http.route('/queue/health', type='json', auth='public', csrf=False)
    def health_check(self, **kwargs):
        """Vérification de santé du système avec références"""
        try:
            # Test basique des modèles
            services_count = request.env['queue.service'].sudo().search_count([])
            tickets_count = request.env['queue.ticket'].sudo().search_count([])
            
            # Test des références
            tickets_with_references = request.env['queue.ticket'].sudo().search_count([
                ('ticket_reference', '!=', False)
            ])
            
            # Test de recherche par référence
            reference_search_working = False
            if tickets_with_references > 0:
                try:
                    sample_ticket = request.env['queue.ticket'].sudo().search([
                        ('ticket_reference', '!=', False)
                    ], limit=1)
                    if sample_ticket:
                        found = request.env['queue.ticket'].sudo().find_ticket_by_reference(sample_ticket.ticket_reference)
                        reference_search_working = bool(found)
                except:
                    reference_search_working = False
            
            return {
                'success': True,
                'status': 'healthy',
                'services_count': services_count,
                'tickets_count': tickets_count,
                'tickets_with_references': tickets_with_references,
                'reference_coverage': (tickets_with_references / max(tickets_count, 1)) * 100,
                'reference_search_working': reference_search_working,
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

    @http.route('/queue/maintenance', type='json', auth='user', methods=['POST'], csrf=False)
    def maintenance_operations(self, operation=None, **kwargs):
        """Opérations de maintenance du système"""
        try:
            if not request.env.user.has_group('base.group_user'):
                return {'success': False, 'error': 'Accès non autorisé'}
            
            if operation == 'generate_references':
                count = request.env['queue.ticket'].generate_missing_references()
                return {'success': True, 'message': f'Références générées pour {count} tickets'}
            
            elif operation == 'check_uniqueness':
                result = request.env['queue.ticket'].check_reference_uniqueness()
                return {'success': True, 'result': result}
            
            elif operation == 'cleanup_old_tickets':
                count = request.env['queue.ticket'].cleanup_old_cancelled_tickets(days_to_keep=30)
                return {'success': True, 'message': f'{count} anciens tickets nettoyés'}
            
            elif operation == 'refresh_stats':
                result = request.env['queue.ticket'].bulk_update_statistics()
                return {'success': True, 'result': result}
            
            elif operation == 'scheduled_maintenance':
                result = request.env['queue.ticket'].scheduled_data_maintenance()
                return {'success': True, 'result': result}
            
            else:
                return {'success': False, 'error': 'Opération non reconnue'}
                
        except Exception as e:
            _logger.error(f"Erreur maintenance {operation}: {e}")
            return {'success': False, 'error': str(e)}

    # ========================================
    # ROUTES DE TEST ET DEBUG
    # ========================================
    
    @http.route('/queue/test', type='http', auth='public', website=True)
    def test_basic_functionality(self, **kwargs):
        """Page de test basique pour vérifier le bon fonctionnement"""
        try:
            services = request.env['queue.service'].sudo().search([('active', '=', True)], limit=5)
            
            # Test de génération de référence
            test_reference = None
            test_short_reference = None
            if services:
                try:
                    test_vals = {'service_id': services[0].id, 'ticket_number': 999}
                    test_reference = request.env['queue.ticket']._generate_unique_reference(test_vals)
                    test_short_reference = request.env['queue.ticket']._generate_short_reference(test_vals)
                except Exception as e:
                    _logger.warning(f"Test référence échoué: {e}")
            
            html_content = f"""
            <div class="container mt-4">
                <h1>Test Queue Management avec Références</h1>
                <div class="alert alert-success">
                    <h4>✅ Système fonctionnel!</h4>
                    <p>Services trouvés: {len(services)}</p>
                </div>
                
                <div class="card mt-3">
                    <div class="card-header">
                        <h5>Test des Références</h5>
                    </div>
                    <div class="card-body">
                        <p><strong>Référence test:</strong> {test_reference or 'Erreur génération'}</p>
                        <p><strong>Référence courte test:</strong> {test_short_reference or 'Erreur génération'}</p>
                    </div>
                </div>
                
                <ul class="list-group mt-3">
            """
            
            for service in services:
                html_content += f"""
                    <li class="list-group-item d-flex justify-content-between align-items-center">
                        <div>
                            <strong>{service.name}</strong>
                            <br><small>ID: {service.id}</small>
                        </div>
                        <span class="badge bg-{'success' if service.is_open else 'danger'}">
                            {'Ouvert' if service.is_open else 'Fermé'}
                        </span>
                    </li>
                """
            
            html_content += """
                </ul>
                <div class="mt-3">
                    <a href="/queue" class="btn btn-primary">Aller à la page principale</a>
                    <a href="/queue/search" class="btn btn-secondary">Test recherche</a>
                    <a href="/queue/admin" class="btn btn-info">Administration</a>
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

    # ========================================
    # ROUTES QR CODE ET MOBILE
    # ========================================
    
    @http.route('/queue/qr/<reference>', type='http', auth='public')
    def qr_redirect(self, reference, **kwargs):
        """Redirection depuis QR code vers suivi ticket"""
        try:
            # Vérifier si la référence existe
            ticket = request.env['queue.ticket'].sudo().find_ticket_by_reference(reference)
            
            if ticket:
                return request.redirect(f'/queue/track/{reference}')
            else:
                return request.render('queue_management.error_template', {
                    'error_message': f'Ticket avec référence {reference} non trouvé'
                })
                
        except Exception as e:
            _logger.error(f"Erreur QR redirect {reference}: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors de la redirection QR'
            })

    @http.route('/queue/mobile/<reference>', type='http', auth='public', website=True)
    def mobile_ticket_view(self, reference, **kwargs):
        """Vue mobile optimisée pour le suivi de ticket"""
        try:
            result = request.env['queue.ticket'].sudo().get_ticket_by_reference_web(reference)
            
            if not result['success']:
                return request.render('queue_management.mobile_error_template', {
                    'error_message': result.get('error', 'Ticket non trouvé')
                })
            
            ticket_data = result['ticket']
            ticket = request.env['queue.ticket'].sudo().browse(ticket_data['id'])
            
            return request.render('queue_management.mobile_ticket_template', {
                'ticket': ticket,
                'ticket_data': ticket_data,
                'reference': reference
            })
            
        except Exception as e:
            _logger.error(f"Erreur vue mobile {reference}: {e}")
            return request.render('queue_management.mobile_error_template', {
                'error_message': 'Erreur lors du chargement'
            })

    # ========================================
    # ROUTES D'EXPORT ET REPORTING
    # ========================================
    
    @http.route('/queue/export/tickets', type='http', auth='user', methods=['GET'])
    def export_tickets_csv(self, date_from=None, date_to=None, service_id=None, **kwargs):
        """Export CSV des tickets avec références"""
        try:
            if not request.env.user.has_group('base.group_user'):
                return request.make_response("Accès non autorisé", status=403)
            
            # Construire le domaine de recherche
            domain = []
            
            if date_from:
                domain.append(('created_time', '>=', date_from))
            else:
                domain.append(('created_time', '>=', fields.Date.today()))
                
            if date_to:
                domain.append(('created_time', '<=', date_to))
                
            if service_id:
                domain.append(('service_id', '=', int(service_id)))
            
            tickets = request.env['queue.ticket'].sudo().search(domain)
            
            # Préparer les données CSV
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # En-têtes
            headers = [
                'Référence', 'Référence Courte', 'Numéro', 'Service', 'État',
                'Client', 'Téléphone', 'Email', 'Date Création', 
                'Temps Attente (min)', 'Position', 'Hash Sécurité'
            ]
            writer.writerow(headers)
            
            # Données
            for ticket in tickets:
                row = [
                    getattr(ticket, 'ticket_reference', ''),
                    getattr(ticket, 'short_reference', ''),
                    ticket.ticket_number,
                    ticket.service_id.name,
                    ticket.state,
                    ticket.customer_name or '',
                    ticket.customer_phone or '',
                    ticket.customer_email or '',
                    ticket.created_time.strftime('%d/%m/%Y %H:%M') if ticket.created_time else '',
                    ticket.waiting_time or 0,
                    ticket.get_queue_position() if hasattr(ticket, 'get_queue_position') else 0,
                    getattr(ticket, 'security_hash', '')[:8] + '...' if getattr(ticket, 'security_hash', '') else ''
                ]
                writer.writerow(row)
            
            # Préparer la réponse
            csv_data = output.getvalue()
            output.close()
            
            filename = f"tickets_{fields.Date.today().strftime('%Y%m%d')}.csv"
            
            return request.make_response(
                csv_data,
                headers=[
                    ('Content-Type', 'text/csv; charset=utf-8'),
                    ('Content-Disposition', f'attachment; filename={filename}')
                ]
            )
            
        except Exception as e:
            _logger.error(f"Erreur export CSV: {e}")
            return request.make_response(f"Erreur export: {str(e)}", status=500)

    # ========================================
    # ROUTES DE FEEDBACK AMÉLIORÉES
    # ========================================
    
    @http.route([
        '/queue/feedback/<reference>',
        '/queue/feedback/<int:ticket_id>'
    ], type='http', auth='public', website=True, methods=['GET', 'POST'])
    def ticket_feedback(self, reference=None, ticket_id=None, **kwargs):
        """Page de feedback pour un ticket"""
        try:
            ticket = None
            
            # Recherche par référence ou ID
            if reference:
                ticket = request.env['queue.ticket'].sudo().find_ticket_by_reference(reference)
            elif ticket_id:
                ticket = request.env['queue.ticket'].sudo().browse(ticket_id)
            
            if not ticket or not ticket.exists() or ticket.state != 'served':
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
                    
                    # Log du feedback
                    _logger.info(f"Feedback reçu pour ticket {ticket.ticket_reference or ticket.id}: {rating}/5")
                    
                    return request.render('queue_management.feedback_thanks_template', {
                        'ticket': ticket,
                        'service': ticket.service_id,
                        'reference': reference
                    })
            
            return request.render('queue_management.feedback_form_template', {
                'ticket': ticket,
                'service': ticket.service_id,
                'reference': reference
            })
            
        except Exception as e:
            _logger.error(f"Erreur feedback: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors du traitement du feedback'
            })

    # ========================================
    # WEBSOCKET ET TEMPS RÉEL (si nécessaire)
    # ========================================
    
    @http.route('/queue/live_updates/<reference>', type='json', auth='public', csrf=False)
    def get_live_updates(self, reference, **kwargs):
        """Obtenir les mises à jour en temps réel pour un ticket"""
        try:
            result = request.env['queue.ticket'].sudo().get_ticket_by_reference_web(reference)
            
            if result['success']:
                ticket_data = result['ticket']
                
                # Ajouter des informations temps réel
                service = request.env['queue.service'].sudo().browse(ticket_data.get('service_id'))
                if service:
                    ticket_data['service_current_ticket'] = service.current_ticket_number or 0
                    ticket_data['service_waiting_count'] = len(service.waiting_ticket_ids)
                
                # Calculer le temps restant estimé
                if ticket_data['position'] > 0:
                    avg_service_time = getattr(service, 'avg_service_time', 5)
                    ticket_data['estimated_remaining_time'] = ticket_data['position'] * avg_service_time
                
                return {
                    'success': True,
                    'data': ticket_data,
                    'timestamp': fields.Datetime.now().isoformat()
                }
            else:
                return result
                
        except Exception as e:
            _logger.error(f"Erreur live updates {reference}: {e}")
            return {'success': False, 'error': 'Erreur lors de la mise à jour'}

    # ========================================
    # ROUTE DE MIGRATION (UTILITAIRE ADMIN)
    # ========================================
    
    @http.route('/queue/migrate_references', type='http', auth='user', methods=['GET', 'POST'])
    def migrate_to_references(self, **kwargs):
        """Page de migration vers le système de références"""
        try:
            if not request.env.user.has_group('base.group_system'):
                return request.make_response("Accès administrateur requis", status=403)
            
            if request.httprequest.method == 'POST':
                # Effectuer la migration
                try:
                    count = request.env['queue.ticket'].generate_missing_references()
                    
                    return f"""
                    <div class="container mt-4">
                        <div class="alert alert-success">
                            <h4>✅ Migration terminée!</h4>
                            <p>Références générées pour {count} tickets.</p>
                            <a href="/queue/admin/references" class="btn btn-primary">Voir les références</a>
                        </div>
                    </div>
                    """
                except Exception as e:
                    return f"""
                    <div class="container mt-4">
                        <div class="alert alert-danger">
                            <h4>❌ Erreur de migration</h4>
                            <p>Erreur: {str(e)}</p>
                        </div>
                    </div>
                    """
            
            # Afficher la page de migration
            stats = {
                'total_tickets': request.env['queue.ticket'].search_count([]),
                'tickets_with_references': request.env['queue.ticket'].search_count([('ticket_reference', '!=', False)])
            }
            
            return f"""
            <div class="container mt-4">
                <div class="card">
                    <div class="card-header">
                        <h4>Migration vers le système de références uniques</h4>
                    </div>
                    <div class="card-body">
                        <p><strong>Tickets totaux:</strong> {stats['total_tickets']}</p>
                        <p><strong>Tickets avec références:</strong> {stats['tickets_with_references']}</p>
                        <p><strong>Tickets à migrer:</strong> {stats['total_tickets'] - stats['tickets_with_references']}</p>
                        
                        <form method="post" class="mt-3">
                            <button type="submit" class="btn btn-primary" 
                                    onclick="return confirm('Confirmer la migration ?')">
                                Démarrer la migration
                            </button>
                            <a href="/queue/admin" class="btn btn-secondary">Retour</a>
                        </form>
                    </div>
                </div>
            </div>
            """
            
        except Exception as e:
            _logger.error(f"Erreur migration: {e}")
            return request.make_response(f"Erreur: {str(e)}", status=500)

    # ========================================
    # NOUVELLES ROUTES POUR L'ADMIN - COMPLÉMENTAIRES
    # ========================================

    @http.route('/queue/admin/call_next', type='json', auth='user', methods=['POST'], csrf=False)
    def admin_call_next_ticket(self, service_id, **kwargs):
        """Appeler le prochain ticket pour un service - CORRIGÉ POUR ODOO 17"""
        try:
            if not request.env.user.has_group('base.group_user'):
                return {'success': False, 'error': 'Accès non autorisé'}
            
            service = request.env['queue.service'].sudo().browse(int(service_id))
            if not service.exists():
                return {'success': False, 'error': 'Service non trouvé'}
            
            if not service.is_open:
                return {'success': False, 'error': 'Service fermé'}
            
            # Appeler le prochain ticket
            next_ticket = service.action_call_next_ticket()
            
            if next_ticket:
                return {
                    'success': True,
                    'message': f'Ticket #{next_ticket.ticket_number} appelé pour {service.name}',
                    'ticket_number': next_ticket.ticket_number,
                    'ticket_reference': getattr(next_ticket, 'ticket_reference', '')
                }
            else:
                return {'success': False, 'error': 'Aucun ticket en attente'}
                
        except Exception as e:
            _logger.error(f"Erreur appel prochain ticket: {e}")
            return {'success': False, 'error': f'Erreur: {str(e)}'}

    @http.route('/queue/admin/service/<int:service_id>/tickets', type='http', auth='user', website=True)
    def admin_service_tickets(self, service_id, **kwargs):
        """Voir les tickets d'un service spécifique"""
        try:
            if not request.env.user.has_group('base.group_user'):
                return request.render('website.403')
            
            service = request.env['queue.service'].sudo().browse(service_id)
            if not service.exists():
                return request.render('queue_management.error_template', {
                    'error_message': 'Service non trouvé'
                })
            
            # Tickets en attente
            waiting_tickets = request.env['queue.ticket'].sudo().search([
                ('service_id', '=', service_id),
                ('state', '=', 'waiting')
            ], order='ticket_number')
            
            # Tickets appelés aujourd'hui
            called_today = request.env['queue.ticket'].sudo().search([
                ('service_id', '=', service_id),
                ('state', '=', 'called'),
                ('called_time', '>=', fields.Date.today())
            ], order='called_time desc', limit=20)
            
            return request.render('queue_management.admin_service_tickets_template', {
                'service': service,
                'waiting_tickets': waiting_tickets,
                'called_today': called_today
            })
            
        except Exception as e:
            _logger.error(f"Erreur tickets service {service_id}: {e}")
            return request.render('queue_management.error_template', {
                'error_message': 'Erreur lors du chargement des tickets'
            })