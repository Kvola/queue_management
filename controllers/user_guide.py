# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.home import Home


class QueueGuideController(http.Controller):
    """Contrôleur pour le guide utilisateur du module Queue Manager"""

    @http.route('/web/queue-guide', type='http', auth='user', website=False)
    def queue_guide_home(self, **kwargs):
        """Page d'accueil du guide utilisateur"""
        return request.render('queue_management.queue_user_guide_template', {
            'page_title': 'Guide Utilisateur - Gestionnaire de Files d\'Attente',
            'active_menu': 'home'
        })

    @http.route('/web/queue-guide/installation', type='http', auth='user', website=False)
    def queue_guide_installation(self, **kwargs):
        """Guide d'installation du module"""
        return request.render('queue_management.queue_installation_template', {
            'page_title': 'Installation du Module',
            'active_menu': 'installation'
        })

    @http.route('/web/queue-guide/configuration', type='http', auth='user', website=False)
    def queue_guide_configuration(self, **kwargs):
        """Guide de configuration du système"""
        return request.render('queue_management.queue_configuration_template', {
            'page_title': 'Configuration du Système',
            'active_menu': 'configuration'
        })

    @http.route('/web/queue-guide/services', type='http', auth='user', website=False)
    def queue_guide_services(self, **kwargs):
        """Guide de gestion des services"""
        return request.render('queue_management.queue_services_template', {
            'page_title': 'Gestion des Services',
            'active_menu': 'services'
        })

    @http.route('/web/queue-guide/tickets', type='http', auth='user', website=False)
    def queue_guide_tickets(self, **kwargs):
        """Guide de gestion des tickets"""
        return request.render('queue_management.queue_tickets_template', {
            'page_title': 'Gestion des Tickets',
            'active_menu': 'tickets'
        })

    @http.route('/web/queue-guide/dashboard', type='http', auth='user', website=False)
    def queue_guide_dashboard(self, **kwargs):
        """Guide du tableau de bord"""
        return request.render('queue_management.queue_dashboard_template', {
            'page_title': 'Tableau de Bord',
            'active_menu': 'dashboard'
        })

    @http.route('/web/queue-guide/reports', type='http', auth='user', website=False)
    def queue_guide_reports(self, **kwargs):
        """Guide des rapports et analyses"""
        return request.render('queue_management.queue_reports_template', {
            'page_title': 'Rapports et Analyses',
            'active_menu': 'reports'
        })

    @http.route('/web/queue-guide/api', type='http', auth='user', website=False)
    def queue_guide_api(self, **kwargs):
        """Documentation API (optionnel)"""
        api_endpoints = [
            {
                'endpoint': '/api/v1/services',
                'method': 'GET',
                'description': 'Liste des services disponibles',
                'params': ['active_only', 'include_stats']
            },
            {
                'endpoint': '/api/v1/tickets',
                'method': 'POST',
                'description': 'Création d\'un nouveau ticket',
                'params': ['service_id', 'client_name', 'client_phone', 'priority']
            },
            {
                'endpoint': '/api/v1/tickets/{ticket_id}/status',
                'method': 'GET',
                'description': 'Statut d\'un ticket spécifique',
                'params': []
            },
            {
                'endpoint': '/api/v1/queue/stats',
                'method': 'GET',
                'description': 'Statistiques des files d\'attente',
                'params': ['service_id', 'date_from', 'date_to']
            }
        ]
        
        return request.render('queue_management.queue_api_template', {
            'page_title': 'Documentation API',
            'active_menu': 'api',
            'api_endpoints': api_endpoints
        })

    @http.route('/web/queue-guide/print/<string:section>', type='http', auth='user', website=False)
    def queue_guide_print(self, section, **kwargs):
        """Version imprimable d'une section du guide"""
        template_mapping = {
            'home': 'queue_user_guide_template',
            'installation': 'queue_installation_template',
            'configuration': 'queue_configuration_template',
            'services': 'queue_services_template',
            'tickets': 'queue_tickets_template',
            'dashboard': 'queue_dashboard_template',
            'reports': 'queue_reports_template'
        }
        
        template_name = template_mapping.get(section)
        if not template_name:
            return request.not_found()
        
        return request.render(f'queue_management.{template_name}', {
            'page_title': f'Guide Utilisateur - {section.title()}',
            'print_mode': True,
            'active_menu': section
        })

    @http.route('/web/queue-guide/pdf/<string:section>', type='http', auth='user', website=False)
    def queue_guide_pdf(self, section, **kwargs):
        """Export PDF d'une section du guide"""
        try:
            # Import des modules nécessaires pour la génération PDF
            import io
            import base64
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            
            # Création du buffer PDF
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            styles = getSampleStyleSheet()
            story = []
            
            # Contenu basé sur la section
            title = f"Guide Utilisateur - {section.title()}"
            story.append(Paragraph(title, styles['Title']))
            story.append(Spacer(1, 12))
            
            # Génération du PDF
            doc.build(story)
            pdf_data = buffer.getvalue()
            buffer.close()
            
            # Retour de la réponse PDF
            response = request.make_response(
                pdf_data,
                headers=[
                    ('Content-Type', 'application/pdf'),
                    ('Content-Disposition', f'attachment; filename="guide_queue_{section}.pdf"')
                ]
            )
            return response
            
        except ImportError:
            # Fallback si reportlab n'est pas installé
            return request.render('queue_management.error_template', {
                'error_title': 'Module manquant',
                'error_message': 'Le module reportlab est requis pour générer des PDF.'
            })

    @http.route('/web/queue-guide/search', type='json', auth='user', website=False)
    def queue_guide_search(self, query='', **kwargs):
        """Recherche dans le guide utilisateur"""
        if not query or len(query) < 3:
            return {'results': []}
        
        # Simulation de résultats de recherche
        # En production, ceci pourrait rechercher dans le contenu des templates
        mock_results = [
            {
                'title': 'Installation du Module',
                'url': '/web/queue-guide/installation',
                'section': 'installation',
                'excerpt': 'Guide complet d\'installation et de première configuration...'
            },
            {
                'title': 'Configuration des Services',
                'url': '/web/queue-guide/services',
                'section': 'services',
                'excerpt': 'Création et gestion des services avec horaires et capacités...'
            },
            {
                'title': 'Gestion des Tickets',
                'url': '/web/queue-guide/tickets',
                'section': 'tickets',
                'excerpt': 'Suivi temps réel des tickets et gestion des files d\'attente...'
            }
        ]
        
        # Filtrage basique basé sur la requête
        results = [
            result for result in mock_results
            if query.lower() in result['title'].lower() or 
               query.lower() in result['excerpt'].lower()
        ]
        
        return {'results': results}

    @http.route('/web/queue-guide/feedback', type='json', auth='user', website=False)
    def queue_guide_feedback(self, section='', rating=0, comment='', **kwargs):
        """Collecte de feedback sur le guide utilisateur"""
        try:
            # Enregistrement du feedback
            user = request.env.user
            feedback_data = {
                'user_id': user.id,
                'section': section,
                'rating': int(rating),
                'comment': comment,
                'date': http.fields.Datetime.now()
            }
            
            # En production, sauvegarder en base de données
            #request.env['queue.guide.feedback'].create(feedback_data)
            
            return {
                'success': True,
                'message': 'Merci pour votre feedback !'
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur lors de l\'enregistrement: {str(e)}'
            }

    @http.route('/web/queue-guide/menu-data', type='json', auth='user', website=False)
    def queue_guide_menu_data(self, **kwargs):
        """Données pour le menu de navigation"""
        menu_items = [
            {
                'id': 'home',
                'name': 'Accueil',
                'url': '/web/queue-guide',
                'icon': 'fa-home',
                'description': 'Vue d\'ensemble du guide'
            },
            {
                'id': 'installation',
                'name': 'Installation',
                'url': '/web/queue-guide/installation',
                'icon': 'fa-cog',
                'description': 'Guide d\'installation du module'
            },
            {
                'id': 'configuration',
                'name': 'Configuration',
                'url': '/web/queue-guide/configuration',
                'icon': 'fa-wrench',
                'description': 'Configuration du système'
            },
            {
                'id': 'services',
                'name': 'Services',
                'url': '/web/queue-guide/services',
                'icon': 'fa-list',
                'description': 'Gestion des services'
            },
            {
                'id': 'tickets',
                'name': 'Tickets',
                'url': '/web/queue-guide/tickets',
                'icon': 'fa-ticket-alt',
                'description': 'Gestion des tickets'
            },
            {
                'id': 'dashboard',
                'name': 'Tableau de Bord',
                'url': '/web/queue-guide/dashboard',
                'icon': 'fa-chart-line',
                'description': 'Utilisation du tableau de bord'
            },
            {
                'id': 'reports',
                'name': 'Rapports',
                'url': '/web/queue-guide/reports',
                'icon': 'fa-file-alt',
                'description': 'Génération de rapports'
            }
        ]
        
        return {'menu_items': menu_items}

class HomeWithUserGuide(Home):
    def _prepare_home_menu(self):
        menu = super(HomeWithUserGuide, self)._prepare_home_menu()
        menu['guide'] = {
            'sequence': 70,
            'url': '/web/queue-guide',
            'title': 'Guide Utilisateur',
        }
        return menu