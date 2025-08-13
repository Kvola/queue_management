# controllers/main.py
from odoo import http, fields
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class QueueController(http.Controller):
    
    @http.route('/queue', type='http', auth='public', website=True)
    def queue_main(self):
        """Page principale des files d'attente"""
        services = request.env['queue.service'].sudo().search([('active', '=', True)])
        return request.render('queue_management.queue_main_template', {
            'services': services
        })
    
    @http.route('/queue/service/<int:service_id>', type='http', auth='public', website=True)
    def queue_service_detail(self, service_id):
        """Détail d'un service avec file d'attente"""
        service = request.env['queue.service'].sudo().browse(service_id)
        if not service.exists():
            return request.not_found()
        
        waiting_tickets = service.waiting_ticket_ids.sorted('ticket_number')
        return request.render('queue_management.queue_service_template', {
            'service': service,
            'waiting_tickets': waiting_tickets
        })
    
    # Route HTTP pour prendre un ticket (formulaire standard)
    @http.route('/queue/take_ticket_http', type='http', auth='public', methods=['POST'], csrf=False, website=True)
    def take_ticket_http(self, service_id, customer_phone='', customer_email='', customer_name='', **kwargs):
        """Prendre un ticket via formulaire HTTP"""
        try:
            # Validation des paramètres
            if not service_id:
                return request.render('queue_management.error_template', {
                    'error_message': 'ID du service requis'
                })
            
            service = request.env['queue.service'].sudo().browse(int(service_id))
            if not service.exists():
                return request.render('queue_management.error_template', {
                    'error_message': 'Service non trouvé'
                })
            
            if not service.is_open:
                return request.render('queue_management.error_template', {
                    'error_message': 'Service actuellement fermé'
                })
            
            # Préparer les données client
            ticket_data = {
                'service_id': service.id,
            }
            if customer_phone:
                ticket_data['customer_phone'] = customer_phone.strip()
            if customer_email:
                ticket_data['customer_email'] = customer_email.strip()
            if customer_name:
                ticket_data['customer_name'] = customer_name.strip()
            
            # Créer le ticket
            ticket = request.env['queue.ticket'].sudo().create(ticket_data)
            
            # Calculer la position dans la file
            tickets_before_count = request.env['queue.ticket'].sudo().search_count([
                ('service_id', '=', service.id),
                ('state', '=', 'waiting'),
                ('ticket_number', '<', ticket.ticket_number)
            ])
            position = tickets_before_count + 1
            
            # Rediriger vers la page de confirmation avec le ticket
            return request.redirect(f'/queue/ticket_confirmation/{ticket.id}')
            
        except ValueError as e:
            _logger.error(f"Erreur de validation lors de la prise de ticket: {str(e)}")
            return request.render('queue_management.error_template', {
                'error_message': 'Données invalides fournies'
            })
        except Exception as e:
            _logger.error(f"Erreur lors de la prise de ticket: {str(e)}")
            return request.render('queue_management.error_template', {
                'error_message': 'Une erreur est survenue lors de la génération du ticket'
            })

    @http.route('/queue/ticket_confirmation/<int:ticket_id>', type='http', auth='public', website=True)
    def ticket_confirmation(self, ticket_id):
        """Page de confirmation après création d'un ticket"""
        ticket = request.env['queue.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return request.render('queue_management.error_template', {
                'error_message': 'Ticket non trouvé'
            })
        
        # Calculer la position actuelle dans la file
        tickets_before_count = request.env['queue.ticket'].sudo().search_count([
            ('service_id', '=', ticket.service_id.id),
            ('state', '=', 'waiting'),
            ('ticket_number', '<', ticket.ticket_number)
        ])
        position = tickets_before_count + 1 if ticket.state == 'waiting' else 0
        
        return request.render('queue_management.ticket_confirmation_template', {
            'ticket': ticket,
            'service': ticket.service_id,
            'position': position,
            'track_url': f'/queue/my_ticket/{ticket.ticket_number}/{ticket.service_id.id}'
        })

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

    @http.route('/queue/take_ticket', type='json', auth='public', methods=['POST'], csrf=False)
    def take_ticket(self, service_id, customer_phone='', customer_email='', customer_name='', **kwargs):
        """Prendre un ticket via API JSON"""
        try:
            # Validation des paramètres
            if not service_id:
                return {'error': 'ID du service requis'}
            
            service = request.env['queue.service'].sudo().browse(int(service_id))
            if not service.exists():
                return {'error': 'Service non trouvé'}
            
            if not service.is_open:
                return {'error': 'Service actuellement fermé'}
            
            # Préparer les données client
            ticket_data = {
                'service_id': service.id,
            }
            if customer_phone:
                ticket_data['customer_phone'] = customer_phone.strip()
            if customer_email:
                ticket_data['customer_email'] = customer_email.strip()
            if customer_name:
                ticket_data['customer_name'] = customer_name.strip()
            
            # Créer le ticket
            ticket = request.env['queue.ticket'].sudo().create(ticket_data)
            
            # Calculer la position dans la file
            position = len(service.waiting_ticket_ids.filtered(lambda t: t.ticket_number < ticket.ticket_number)) + 1
            
            return {
                'success': True,
                'ticket_number': ticket.ticket_number,
                'estimated_wait': ticket.estimated_wait_time,
                'position': position,
                'service_name': service.name
            }
            
        except ValueError as e:
            _logger.error(f"Erreur de validation lors de la prise de ticket: {str(e)}")
            return {'error': 'Données invalides fournies'}
        except Exception as e:
            _logger.error(f"Erreur lors de la prise de ticket: {str(e)}")
            return {'error': 'Une erreur est survenue lors de la génération du ticket'}
    
    @http.route('/queue/status/<int:service_id>', type='json', auth='public', csrf=False)
    def queue_status(self, service_id):
        """Statut temps réel d'une file d'attente"""
        try:
            service = request.env['queue.service'].sudo().browse(service_id)
            if not service.exists():
                return {'error': 'Service non trouvé'}
            
            waiting_tickets = service.waiting_ticket_ids.sorted('ticket_number')
            return {
                'service_name': service.name,
                'waiting_count': len(waiting_tickets),
                'current_ticket': service.current_ticket_number,
                'is_open': service.is_open,
                'tickets': [{
                    'number': t.ticket_number,
                    'estimated_wait': t.estimated_wait_time
                } for t in waiting_tickets[:10]]  # Limite à 10 pour performance
            }
        except Exception as e:
            _logger.error(f"Erreur lors de la récupération du statut: {str(e)}")
            return {'error': 'Erreur lors de la récupération du statut'}

    @http.route('/queue/admin', type='http', auth='user', website=True)
    def admin_dashboard(self):
        """Interface d'administration web pour les agents"""
        if not request.env.user.has_group('queue_management.group_queue_user'):
            return request.render('website.403')
        
        services = request.env['queue.service'].search([('active', '=', True)])
        return request.render('queue_management.admin_dashboard_template', {
            'services': services
        })

    @http.route('/queue/admin/action', type='json', auth='user', methods=['POST'], csrf=False)
    def admin_action(self, action, ticket_id=None, service_id=None, **kwargs):
        """Actions d'administration via AJAX"""
        if not request.env.user.has_group('queue_management.group_queue_user'):
            return {'error': 'Accès non autorisé'}
        
        try:
            if action == 'call_next' and ticket_id:
                ticket = request.env['queue.ticket'].browse(int(ticket_id))
                if not ticket.exists():
                    return {'error': 'Ticket non trouvé'}
                
                ticket.action_call_next()
                return {'success': True, 'message': f'Ticket #{ticket.ticket_number} appelé'}
            
            elif action == 'complete_service' and ticket_id:
                ticket = request.env['queue.ticket'].browse(int(ticket_id))
                if not ticket.exists():
                    return {'error': 'Ticket non trouvé'}
                
                ticket.action_complete_service()
                return {'success': True, 'message': f'Service ticket #{ticket.ticket_number} terminé'}
            
            elif action == 'generate_ticket' and service_id:
                service = request.env['queue.service'].browse(int(service_id))
                if not service.exists():
                    return {'error': 'Service non trouvé'}
                
                # Créer un ticket directement
                ticket = request.env['queue.ticket'].create({
                    'service_id': service.id
                })
                return {'success': True, 'message': f'Nouveau ticket #{ticket.ticket_number} généré'}
            
            elif action == 'toggle_service' and service_id:
                service = request.env['queue.service'].browse(int(service_id))
                if not service.exists():
                    return {'error': 'Service non trouvé'}
                
                service.is_open = not service.is_open
                status = "ouvert" if service.is_open else "fermé"
                return {'success': True, 'message': f'Service {status}'}
            
            else:
                return {'error': 'Action non reconnue ou paramètres manquants'}
                
        except ValueError as e:
            _logger.error(f"Erreur de validation dans admin_action: {str(e)}")
            return {'error': 'Données invalides fournies'}
        except Exception as e:
            _logger.error(f"Erreur dans admin_action: {str(e)}")
            return {'error': 'Une erreur est survenue lors de l\'exécution de l\'action'}


    # Ajout dans controllers/main.py
    @http.route('/queue/print_ticket/<int:ticket_id>', type='http', auth='public', website=False)
    def print_ticket(self, ticket_id):
        """Version imprimable du ticket sans layout"""
        ticket = request.env['queue.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return request.not_found()
        
        # Calculer la position
        tickets_before_count = request.env['queue.ticket'].sudo().search_count([
            ('service_id', '=', ticket.service_id.id),
            ('state', '=', 'waiting'),
            ('ticket_number', '<', ticket.ticket_number)
        ])
        position = tickets_before_count + 1 if ticket.state == 'waiting' else 0
        
        # Utiliser le template sans layout (website=False)
        return request.render('queue_management.print_ticket_template', {
            'ticket': ticket,
            'service': ticket.service_id,
            'position': position,
            'print_time': fields.Datetime.now()
        }, headers={'Content-Type': 'text/html; charset=utf-8'})

    @http.route('/queue/print_ticket_minimal/<int:ticket_id>', type='http', auth='public', website=False)
    def print_ticket_minimal(self, ticket_id):
        """Version ultra-minimaliste pour impression directe"""
        ticket = request.env['queue.ticket'].sudo().browse(ticket_id)
        if not ticket.exists():
            return request.not_found()
        
        # Calculer la position
        tickets_before_count = request.env['queue.ticket'].sudo().search_count([
            ('service_id', '=', ticket.service_id.id),
            ('state', '=', 'waiting'),
            ('ticket_number', '<', ticket.ticket_number)
        ])
        position = tickets_before_count + 1 if ticket.state == 'waiting' else 0
        
        # Template minimal qui s'imprime automatiquement
        return request.render('queue_management.print_ticket_minimal', {
            'ticket': ticket,
            'service': ticket.service_id,
            'position': position,
            'print_time': fields.Datetime.now()
        }, headers={'Content-Type': 'text/html; charset=utf-8'})

    # Optionnel: Route pour impression popup
    @http.route('/queue/print_popup/<int:ticket_id>', type='http', auth='public', website=False)
    def print_ticket_popup(self, ticket_id):
        """Ouvre le ticket dans une popup pour impression"""
        return f"""
        <script>
            var printWindow = window.open('/queue/print_ticket_minimal/{ticket_id}', 'print', 'width=400,height=600');
            printWindow.onload = function() {{
                printWindow.print();
                printWindow.onafterprint = function() {{
                    printWindow.close();
                }}
            }}
        </script>
        <p>Ouverture de la fenêtre d'impression...</p>
        """

    # Corrections à ajouter dans controllers/main.py
    @http.route('/queue/cancel_ticket', type='json', auth='public', methods=['POST'], csrf=False)
    def cancel_ticket(self, ticket_number, service_id, reason='', **kwargs):
        """Annuler un ticket via l'interface publique"""
        try:
            # Validation des paramètres
            if not ticket_number or not service_id:
                return {'success': False, 'error': 'Numéro de ticket et ID de service requis'}
            
            # Chercher le ticket
            ticket = request.env['queue.ticket'].sudo().search([
                ('ticket_number', '=', int(ticket_number)),
                ('service_id', '=', int(service_id)),
                ('state', 'in', ['waiting', 'called'])
            ], limit=1)
            
            if not ticket:
                return {'success': False, 'error': 'Ticket non trouvé ou déjà traité'}
            
            # Vérifier si l'annulation est autorisée par la configuration
            config = request.env['queue.config'].sudo().search([], limit=1)
            if config and not config.allow_ticket_cancellation:
                return {'success': False, 'error': 'L\'annulation de tickets n\'est pas autorisée'}
            
            # Préparer la raison d'annulation
            if not reason:
                reason = "Annulé par le client via l'interface web"
            else:
                reason = f"Annulé par le client: {reason}"
            
            # Annuler le ticket
            ticket.write({
                'state': 'cancelled',
                'notes': reason,
                'end_time': fields.Datetime.now()
            })
            
            # Log de l'annulation
            _logger.info(f"Ticket #{ticket.ticket_number} du service {ticket.service_id.name} annulé par le client. Raison: {reason}")
            
            return {
                'success': True, 
                'message': f'Ticket #{ticket.ticket_number} annulé avec succès',
                'ticket_number': ticket.ticket_number
            }
            
        except ValueError as e:
            _logger.error(f"Erreur de validation lors de l'annulation: {str(e)}")
            return {'success': False, 'error': 'Données invalides fournies'}
        except Exception as e:
            _logger.error(f"Erreur lors de l'annulation du ticket: {str(e)}")
            return {'success': False, 'error': 'Une erreur est survenue lors de l\'annulation'}

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

    @http.route('/queue/my_ticket/<int:ticket_number>/<int:service_id>', 
                type='http', auth='public', website=True)
    def my_ticket_status(self, ticket_number, service_id):
        """Page de suivi d'un ticket spécifique avec gestion des états"""
        ticket = request.env['queue.ticket'].sudo().search([
            ('ticket_number', '=', ticket_number),
            ('service_id', '=', service_id)
        ], limit=1)
        
        if not ticket:
            return request.render('queue_management.ticket_not_found_template')
        
        # Calculer la position actuelle si le ticket est en attente
        position = 0
        if ticket.state == 'waiting':
            tickets_before_count = request.env['queue.ticket'].sudo().search_count([
                ('service_id', '=', ticket.service_id.id),
                ('state', '=', 'waiting'),
                ('ticket_number', '<', ticket.ticket_number)
            ])
            position = tickets_before_count + 1
            
            # Mettre à jour le temps d'attente estimé
            if position > 0:
                avg_service_time = ticket.service_id.avg_waiting_time or 5
                estimated_wait = position * avg_service_time
                if abs(ticket.estimated_wait_time - estimated_wait) > 2:  # Seulement si différence > 2 min
                    ticket.sudo().write({'estimated_wait_time': estimated_wait})
        
        return request.render('queue_management.my_ticket_template', {
            'ticket': ticket,
            'service': ticket.service_id,
            'position': position
        })