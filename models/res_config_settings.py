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
    # --- Paiement Wave ---
    queue_wave_payment_link = fields.Char(
        related='company_id.wave_payment_link', readonly=False,
        string="Lien de paiement Wave (cette compagnie)",
        help="Lien marchand Wave de la compagnie pour recevoir ses paiements. "
             "Le montant est ajouté automatiquement. Vide → lien par défaut.")
    queue_wave_default_link = fields.Char(
        "Lien Wave par défaut (plateforme)",
        config_parameter='queue_management.wave_default_link',
        help="Utilisé quand une compagnie n'a pas renseigné son propre lien.")
    queue_wave_merchant_label = fields.Char(
        "Numéro / nom Wave Marchand",
        config_parameter='queue_management.wave_merchant_label',
        help="Optionnel — affiché au client si aucun lien Wave n'est disponible.")
    queue_wave_api_key = fields.Char(
        "Clé API Wave (Checkout)",
        config_parameter='queue_management.wave_api_key',
        help="Si renseignée, le paiement Wave devient DIRECT (l'app initie la "
             "transaction, Wave confirme par webhook) — sans validation "
             "guichet. Sinon, repli sur Wave Marchand.")
    queue_wave_webhook_secret = fields.Char(
        "Secret du webhook Wave",
        config_parameter='queue_management.wave_webhook_secret',
        help="Vérifie la signature des notifications Wave. Indispensable pour "
             "la voie directe (sinon le webhook est refusé).")
    queue_no_show_delay_min = fields.Integer(
        "Expiration des RDV non honorés (minutes)", default=60,
        config_parameter='queue_management.no_show_delay_min',
        help="Un rendez-vous non enregistré ce délai après son heure passe "
             "en Absent (le client est prévenu par notification).")
