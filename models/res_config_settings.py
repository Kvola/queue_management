# -*- coding: utf-8 -*-
"""Réglages produit centralisés (Paramètres → File d'attente).

Chaque champ est adossé à un ``ir.config_parameter`` : les valeurs par défaut
historiques (constantes de code) restent les fallbacks — une base existante ne
change pas de comportement tant que l'admin n'a rien touché.
"""
from odoo import fields, models


def int_param(env, key, default):
    """Paramètre système entier, robuste aux valeurs vides/corrompues.

    NB : ``get_param`` renvoie ``False`` quand la clé n'existe pas — et
    ``int(False) == 0``, ce qui écraserait silencieusement le défaut.
    """
    raw = env['ir.config_parameter'].sudo().get_param(key)
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    queue_app_store_url = fields.Char(
        "URL du store de l'app",
        config_parameter='queue_management.app_store_url',
        help="Si renseignée (Play Store…), la page publique /queue/app "
             "redirige vers le store — les QR imprimés restent valables.")
    queue_max_active_tickets = fields.Integer(
        "Tickets actifs max par client", default=5,
        config_parameter='queue_management.max_active_tickets',
        help="Plafond global (files + RDV, tous établissements) par client "
             "mobile — garde anti-abus.")
    queue_token_ttl_days = fields.Integer(
        "Durée de session mobile (jours)", default=90,
        config_parameter='queue_management.token_ttl_days',
        help="Au-delà, l'application redemande une connexion par code email.")
    queue_soon_threshold = fields.Integer(
        "Notification « bientôt votre tour » (position)", default=2,
        config_parameter='queue_management.soon_threshold',
        help="Les clients dont la position atteint ce rang reçoivent la "
             "notification push « Bientôt votre tour ».")
    queue_auto_no_show_min = fields.Integer(
        "Auto-absent des appelés sans réponse (minutes)", default=10,
        config_parameter='queue_management.auto_no_show_min',
        help="Un ticket appelé resté sans réponse ce délai passe en Absent "
             "(guichet libéré, client notifié, re-mise en file possible). "
             "0 = désactivé.")
    queue_no_show_delay_min = fields.Integer(
        "Expiration des RDV non honorés (minutes)", default=60,
        config_parameter='queue_management.no_show_delay_min',
        help="Un rendez-vous non enregistré ce délai après son heure passe "
             "en Absent (le client est prévenu par notification).")
