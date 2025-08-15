# -*- coding: utf-8 -*-
{
    "name": "Gestionnaire de Files d'Attente",
    "version": "17.0.1.0.0",
    "category": "Services",
    "summary": "Gestion des files d'attente clients avec interface web temps réel",
    "description": """
        Module complet de gestion des files d'attente pour services et commerces:
        - Prise de ticket en ligne par les clients
        - Suivi temps réel du nombre de clients en attente
        - Interface admin pour gérer les files d'attente
        - Notifications automatiques
        - Statistiques et rapports
        - Support multi-services
        
INSTALLATION ET CONFIGURATION DU MODULE:

1. INSTALLATION:
   - Copiez le module dans votre répertoire addons
   - Activez le mode développeur dans Odoo
   - Mettez à jour la liste des apps
   - Installez le module "Gestionnaire de Files d'Attente"

2. CONFIGURATION INITIALE:
   - Allez dans Files d'Attente > Configuration
   - Configurez les paramètres généraux (notifications, affichage, etc.)
   - Créez vos services dans Files d'Attente > Services
   - Configurez chaque service (heures, capacité, temps estimé)

3. UTILISATION:
   - Interface Admin: Files d'Attente > Tableau de Bord
   - Interface Client: yoursite.com/queue
   - Suivi individuel: yoursite.com/queue/my_ticket/[numero]/[service_id]

4. PERSONNALISATION:
   - Modifiez les templates dans views/queue_website_templates.xml
   - Adaptez les styles CSS dans static/src/css/
   - Configurez les intégrations SMS/Email selon vos besoins

5. INTÉGRATIONS POSSIBLES:
   - SMS: Intégrez votre provider SMS dans models/queue_ticket.py
   - Push Notifications: Configurez dans models/queue_notification.py
   - Écrans d'affichage: Utilisez l'API JSON pour affichages externes
   - Applications mobiles: Utilisez les endpoints REST disponibles

6. RAPPORTS ET ANALYSES:
   - Rapports automatiques générés quotidiennement
   - Tableaux de bord avec métriques en temps réel
   - Export Excel disponible via l'assistant de rapports
   - API pour intégration avec outils BI externes

FONCTIONNALITÉS PRINCIPALES:
✅ Prise de ticket en ligne
✅ Suivi temps réel
✅ Interface d'administration
✅ Notifications automatiques
✅ Rapports et statistiques
✅ Support multi-services
✅ Gestion des priorités
✅ Système de feedback
✅ API REST complète
✅ Responsive design
✅ Tableau de bord analytique
✅ Codes QR pour suivi
✅ Gestion des pauses/horaires
✅ Système de réservation avancée

Ce module est prêt pour la production et peut être étendu selon vos besoins spécifiques.
""",
    "author": "Votre Entreprise",
    "website": "https://www.votreentreprise.com",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "website",
        "mail",
        "portal",
        "hr",  # Pour intégration avec les employés
        "calendar",  # Pour gestion des créneaux
    ],
    "data": [
        # Sécurité
        "security/queue_security.xml",
        "security/ir.model.access.csv",
        # Données
        "data/queue_data.xml",
        "data/feedback_template.xml",
        # Vues
        "views/queue_service_views.xml",
        "views/queue_ticket_views.xml",
        "views/queue_analytics_views.xml",
        "views/queue_config_views.xml",
        "views/queue_website_templates.xml",
        "reports/queue_reports.xml",
        # Wizards
        "wizard/queue_report_preview_views.xml",
        "wizard/queue_report_wizard_views.xml",
        "wizard/action_maintenance_wizard_views.xml",
        # Rapports
        "views/queue_dashboard_views.xml",
        "views/user_guide_templates.xml",
        "views/queue_menus.xml",

    ],
    "assets": {
        "web.assets_backend": [
            "queue_management/static/src/css/queue_dashboard.css",
            "queue_management/static/src/js/queue_dashboard.js",
            "queue_management/static/src/xml/queue_dashboard.xml",
            "queue_management/static/src/js/user_menu.js",
        ],
        "web.assets_frontend": [
            "queue_management/static/src/css/queue_website.css",
            "queue_management/static/src/js/queue_website.js",
        ],
    },
    "demo": [
        "demo/queue_demo.xml",
    ],
    "external_dependencies": {
        "python": ["qrcode", "requests"],  # Pour QR codes et API externes
    },
    "installable": True,
    "auto_install": False,
    "application": True,
}
