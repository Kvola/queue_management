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

from odoo import _, api, models
from odoo.addons.queue_payment.models.queue_wave import WaveError  # noqa: F401 — ré-export

_logger = logging.getLogger(__name__)

class QueueWaveTicketMixin(models.AbstractModel):
    _inherit = 'queue.wave.mixin'

    @api.model
    def _queue_wave_link(self, company):
        """Lien marchand de la file d'attente : établissement, plateforme,
        puis compte de l'opérateur — la file d'attente encaisse pour lui."""
        return self._wave_operator_link(company)

    @api.model
    def _wave_payment_url(self, ticket):
        """URL Wave prête à payer pour un ticket (lien marchand + montant)."""
        return self._wave_url_from_link(
            self._queue_wave_link(ticket.company_id), ticket.payment_amount)

    def _wave_create_checkout(self, ticket):
        """Ouvre une session de paiement Wave pour un ticket (voie directe).

        La référence de session est rangée dans ``payment_ref`` pour rapprocher
        le webhook. Lève ``WaveError`` en cas d'échec (repli sur Wave Marchand).
        """
        base_url = ticket.get_base_url().rstrip('/')
        # Retour vers le portail du site : il affiche le ticket et son
        # paiement, là où l'ancienne page d'installation de l'app ne disait
        # rien du paiement (et répondait 404 sans version publiée).
        return_url = '%s/queue/u/%s' % (base_url, ticket.location_id.qr_token)
        session_id, url = self._wave_checkout_session(
            ticket.payment_amount,
            ticket.currency_id.name or 'XOF',
            'ticket-%s' % ticket.id,
            return_url,
            # Le compte marchand de l'établissement encaisse, pas celui de la
            # plateforme : sans cela sa clé API n'était jamais utilisée.
            company=ticket.company_id,
        )
        ticket.sudo().write({'payment_ref': session_id})
        return url

    @api.model
    def _wave_handle_webhook(self, event):
        """Traite un événement Wave vérifié : confirme le ticket si payé.

        Ne confirme qu'un ticket qui attend encore son paiement, et pour le
        bon montant quand Wave l'annonce : une notification ne doit pas
        ressusciter un ticket annulé ni solder 5 000 F avec 100 F.
        """
        status, session_id, client_ref = self._wave_event_data(event)
        if status not in ('succeeded', 'success', 'paid'):
            return super()._wave_handle_webhook(event)
        Ticket = self.env['queue.ticket'].sudo()
        # Cloisonnement par société : le secret d'un commerce ne doit pas
        # pouvoir confirmer le ticket payé d'un autre.
        scope = self._wave_company_domain()
        ticket = Ticket.browse()
        if session_id:
            ticket = Ticket.search(
                scope + [('payment_ref', '=', str(session_id))], limit=1)
        if not ticket and client_ref.startswith('ticket-'):
            ticket_id = client_ref.split('-', 1)[1]
            # Une référence mal formée ne doit pas lever : Wave rejouerait
            # sans fin une notification qui échouerait toujours.
            candidate = Ticket.browse(int(ticket_id)).exists() \
                if ticket_id.isdigit() else Ticket.browse()
            ticket = candidate if self._wave_belongs_to_signing_company(
                candidate) else Ticket.browse()
        if not ticket:
            # Peut appartenir à un autre métier (paiement d'événement) : on
            # laisse la chaîne continuer plutôt que de conclure à l'échec.
            return super()._wave_handle_webhook(event)
        if ticket.payment_state == 'paid':
            return True  # rejeu : déjà crédité
        if ticket.state == 'cancelled' or ticket.payment_state not in (
                'pending', 'to_validate'):
            _logger.warning(
                "Webhook Wave : ticket %s (état %s, paiement %s) ignoré",
                ticket.id, ticket.state, ticket.payment_state)
            ticket.message_post(body=_(
                "Notification Wave de paiement reçue alors que le ticket "
                "n'attendait plus de règlement — à vérifier."))
            return True
        data = (event or {}).get('data') or event or {}
        amount = data.get('amount')
        if amount not in (None, ''):
            try:
                received = float(amount)
            except (TypeError, ValueError):
                received = None
            if received is None or received + 0.005 < (ticket.payment_amount or 0):
                _logger.warning(
                    "Webhook Wave : ticket %s, montant reçu %s < dû %s",
                    ticket.id, amount, ticket.payment_amount)
                ticket.message_post(body=_(
                    "Wave annonce un paiement de %(recu)s pour %(du)s dû : "
                    "non confirmé, à vérifier au guichet.",
                    recu=amount, du=ticket._amount_label()))
                return True
        ticket._mark_paid('wave', ref=session_id,
                          by_user=self.env.ref('base.user_root'))
        return True
