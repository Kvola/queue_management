# -*- coding: utf-8 -*-
"""Intégration Wave (paiement mobile) — voie directe optionnelle.

Deux modes selon la configuration (Paramètres → File d'attente) :

* **Wave Marchand** (par défaut) : le client paie sur le numéro Wave du
  marchand depuis l'appli Wave, puis déclare son paiement dans l'app. Un agent
  valide au guichet. Aucune clé API requise.
* **API Wave** (si une clé Checkout est renseignée) : l'app initie une session
  de paiement Wave ; le client paie ; Wave confirme par webhook signé →
  paiement marqué payé automatiquement, sans validation guichet.

L'appel HTTP réel à l'API Wave et la vérification de signature sont implémentés
mais ne peuvent être testés qu'avec un compte marchand Wave (clé + secret).
"""
import hashlib
import hmac
import json
import logging

import requests

from odoo import api, models

_logger = logging.getLogger(__name__)

# API Checkout de Wave. URL surchargée par le paramètre
# queue_management.wave_api_base si besoin (bac à sable).
_WAVE_API_BASE = "https://api.wave.com/v1"
_WAVE_TIMEOUT = 15


class WaveError(Exception):
    """Échec Wave (l'appelant retombe sur Wave Marchand)."""


class QueueWaveMixin(models.AbstractModel):
    _name = 'queue.wave.mixin'
    _description = "Intégration Wave (helpers)"

    @api.model
    def _wave_param(self, name, default=''):
        return (self.env['ir.config_parameter'].sudo()
                .get_param('queue_management.%s' % name) or default).strip()

    @api.model
    def _wave_api_key(self):
        return self._wave_param('wave_api_key')

    @api.model
    def _wave_api_configured(self):
        """L'API Wave est-elle activée ? (voie directe sans validation guichet)"""
        return bool(self._wave_api_key())

    @api.model
    def _wave_merchant_label(self):
        """Numéro/nom Marchand à afficher pour la voie manuelle."""
        return self._wave_param('wave_merchant_label')

    @api.model
    def _wave_api_base(self):
        return self._wave_param('wave_api_base', _WAVE_API_BASE).rstrip('/')

    # ------------------------------------------------------------------
    # Appel API Checkout (voie directe)
    # ------------------------------------------------------------------

    def _wave_create_checkout(self, ticket):
        """Crée une session de paiement Wave et renvoie l'URL de règlement.

        Le client est redirigé vers cette URL (deeplink Wave) ; à la
        confirmation, Wave appelle notre webhook. La référence de session est
        stockée dans ``payment_ref`` pour rapprocher le webhook du ticket.
        Lève ``WaveError`` en cas d'échec (repli sur Wave Marchand).
        """
        key = self._wave_api_key()
        if not key:
            raise WaveError("API Wave non configurée.")
        base_url = (self.env['ir.config_parameter'].sudo()
                    .get_param('web.base.url') or '').rstrip('/')
        payload = {
            'amount': str(int(ticket.payment_amount or 0)),
            'currency': ticket.currency_id.name or 'XOF',
            'error_url': '%s/queue/app' % base_url,
            'success_url': '%s/queue/app' % base_url,
            'client_reference': 'ticket-%s' % ticket.id,
        }
        try:
            resp = requests.post(
                '%s/checkout/sessions' % self._wave_api_base(),
                headers={'Authorization': 'Bearer %s' % key,
                         'Content-Type': 'application/json'},
                data=json.dumps(payload), timeout=_WAVE_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 — repli propre
            _logger.warning("API Wave : échec de création de session : %s", exc)
            raise WaveError(str(exc))
        session_id = data.get('id') or data.get('session_id')
        url = data.get('wave_launch_url') or data.get('payment_url')
        if not (session_id and url):
            raise WaveError("Réponse Wave inattendue.")
        ticket.sudo().write({'payment_ref': session_id})
        return url

    # ------------------------------------------------------------------
    # Webhook (confirmation asynchrone)
    # ------------------------------------------------------------------

    @api.model
    def _wave_verify_signature(self, raw_body, signature):
        """Vérifie la signature HMAC-SHA256 du webhook Wave.

        Sans secret configuré ou sans signature, on refuse : un webhook non
        vérifié permettrait à quiconque de marquer un ticket payé.
        """
        secret = self._wave_param('wave_webhook_secret')
        if not secret or not signature:
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @api.model
    def _wave_handle_webhook(self, event):
        """Traite un événement Wave vérifié : confirme le ticket si payé."""
        data = (event or {}).get('data', {})
        status = data.get('payment_status') or data.get('status')
        session_id = data.get('id') or data.get('session_id')
        client_ref = data.get('client_reference') or ''
        if status not in ('succeeded', 'success', 'paid'):
            return False
        Ticket = self.env['queue.ticket'].sudo()
        ticket = session_id and Ticket.search([('payment_ref', '=', session_id)], limit=1)
        if not ticket and client_ref.startswith('ticket-'):
            ticket = Ticket.browse(int(client_ref.split('-', 1)[1])).exists()
        if not ticket:
            _logger.warning("Webhook Wave : ticket introuvable (session %s)", session_id)
            return False
        ticket._mark_paid('wave', ref=session_id,
                          by_user=self.env.ref('base.user_root'))
        return True
