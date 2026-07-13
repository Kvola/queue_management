# -*- coding: utf-8 -*-
{
    'name': "Gestionnaire de file d'attente",
    'version': '19.0.1.16.0',
    'category': 'Services',
    'summary': "File d'attente virtuelle multi-établissements (hôpitaux, services, administrations)",
    'description': """
Gestionnaire de file d'attente — Phase 0 (socle)
================================================

Solution SaaS multi-clients de gestion de files d'attente pour hôpitaux,
services et administrations.

Phase 0 livrée ici (le socle sur lequel tout repose) :

* Modèle de données : établissement (res.company) → site physique
  (``queue.location``) → file/service (``queue.service``) → guichet
  (``queue.counter``) → ticket (``queue.ticket``).
* Multi-tenant : chaque donnée porte un ``company_id`` et des *record rules*
  garantissent qu'un agent ne voit que sa société.
* Numérotation des tickets par file et par jour (préfixe + compteur réinitialisé
  chaque jour).
* Logique d'appel centralisée : tri par priorité puis ordre d'arrivée, avec
  remontée des rendez-vous dont l'heure est passée.
* Canaux : mobile / borne (kiosk) / rendez-vous.
* QR code de rattachement par site (le client scanne à l'entrée → l'app sait
  où il est).
* Données de démonstration + tests.

Phases suivantes (non incluses) : écran agent & affichage salle d'attente
(Phase 1), API REST + auth email pour le mobile (Phase 2), app Flutter +
push FCM (Phase 3), rendez-vous & borne tactile (Phase 4), estimation du temps
d'attente & statistiques (Phase 5).
    """,
    'author': 'odoo_nineteen',
    'depends': [
        'base',
        'mail',
        # 'push_notification_hub' : dépendance VOLONTAIREMENT souple (non listée).
        # Le push réutilise ce hub quand il est installé, mais queue_management
        # reste installable et fonctionnel sans lui (cf. queue.customer._push).
    ],
    'data': [
        # Sécurité : catégorie + privilège + groupes, puis ACL, puis record rules.
        'security/queue_security.xml',
        'security/ir.model.access.csv',
        'security/queue_record_rules.xml',
        # Catalogue secteurs / modèles de services.
        'data/queue_sectors.xml',
        # Vues & menus.
        'views/queue_location_views.xml',
        'views/queue_service_views.xml',
        'views/queue_counter_views.xml',
        'views/queue_ticket_transfer_views.xml',
        'views/queue_ticket_views.xml',
        'views/queue_display_templates.xml',
        'views/queue_kiosk_templates.xml',
        'views/queue_menus.xml',
        'views/queue_sector_views.xml',
        'views/queue_stats_views.xml',
        'views/queue_customer_views.xml',
        'views/queue_app_release_views.xml',
        'views/queue_app_templates.xml',
        'views/queue_dashboard_views.xml',
        'views/res_config_settings_views.xml',
        'views/queue_setup_wizard_views.xml',
        'views/queue_service_from_template_views.xml',
        'views/queue_help_menus.xml',
        'views/queue_console_views.xml',
        'data/queue_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'queue_management/static/src/dashboard/**/*',
            'queue_management/static/src/console/**/*',
        ],
    },
    'demo': [
        'data/queue_demo.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
