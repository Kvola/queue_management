# -*- coding: utf-8 -*-
"""Extension Wave spécifique au ticket.

Les helpers Wave génériques (lien marchand, session Checkout, signature du
webhook) vivent dans le module ``queue_payment`` (``queue.wave.mixin``). Ici on
ajoute uniquement ce qui touche au **ticket** : construire l'URL de règlement
d'un ticket, ouvrir une session de paiement pour un ticket, et traiter le
webhook Wave en rapprochant la session du ticket concerné.

``WaveError`` est ré-exporté pour conserver le chemin d'import historique
``queue_management.models.queue_wave.WaveError``.
"""
import logging

from odoo import api, models
from odoo.addons.queue_payment.models.queue_wave import WaveError  # noqa: F401 — ré-export

_logger = logging.getLogger(__name__)


class QueueWaveTicketMixin(models.AbstractModel):
    _inherit = 'queue.wave.mixin'

    @api.model
    def _wave_payment_url(self, ticket):
        """URL Wave prête à payer pour un ticket (lien marchand + montant)."""
        return self._wave_url_for(ticket.company_id, ticket.payment_amount)

    def _wave_create_checkout(self, ticket):
        """Ouvre une session de paiement Wave pour un ticket (voie directe).

        La référence de session est rangée dans ``payment_ref`` pour rapprocher
        le webhook. Lève ``WaveError`` en cas d'échec (repli sur Wave Marchand).
        """
        base_url = (self.env['ir.config_parameter'].sudo()
                    .get_param('web.base.url') or '').rstrip('/')
        session_id, url = self._wave_checkout_session(
            ticket.payment_amount,
            ticket.currency_id.name or 'XOF',
            'ticket-%s' % ticket.id,
            '%s/queue/app' % base_url,
        )
        ticket.sudo().write({'payment_ref': session_id})
        return url

    @api.model
    def _wave_handle_webhook(self, event):
        """Traite un événement Wave vérifié : confirme le ticket si payé."""
        data = (event or {}).get('data', {})
        status = data.get('payment_status') or data.get('status')
        session_id = data.get('id') or data.get('session_id')
        client_ref = data.get('client_reference') or ''
        if status not in ('succeeded', 'success', 'paid'):
            return super()._wave_handle_webhook(event)
        Ticket = self.env['queue.ticket'].sudo()
        # Cloisonnement par société : le secret d'un commerce ne doit pas
        # pouvoir confirmer le ticket payé d'un autre.
        scope = self._wave_company_domain()
        ticket = session_id and Ticket.search(
            scope + [('payment_ref', '=', session_id)], limit=1)
        if not ticket and client_ref.startswith('ticket-'):
            candidate = Ticket.browse(int(client_ref.split('-', 1)[1])).exists()
            ticket = candidate if self._wave_belongs_to_signing_company(
                candidate) else Ticket.browse()
        if not ticket:
            # Peut appartenir à un autre métier (paiement d'événement) : on
            # laisse la chaîne continuer plutôt que de conclure à l'échec.
            return super()._wave_handle_webhook(event)
        ticket._mark_paid('wave', ref=session_id,
                          by_user=self.env.ref('base.user_root'))
        return True
