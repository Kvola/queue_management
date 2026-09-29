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

        Le paiement du socle porte la référence de session (``provider_ref``)
        et une clé client unique : le webhook générique du socle le retrouve
        et le confirme, puis prévient le ticket par ses crochets. Lève
        ``WaveError`` en cas d'échec (repli sur Wave Marchand).
        """
        payment = ticket._current_payment('wave')
        if not payment.client_ref:
            payment.client_ref = 'ticket-%s-%s' % (ticket.id, payment.id)
        base_url = ticket.get_base_url().rstrip('/')
        # Retour vers le portail du site : il affiche le ticket et son
        # paiement, là où l'ancienne page d'installation de l'app ne disait
        # rien du paiement (et répondait 404 sans version publiée).
        return_url = '%s/queue/u/%s' % (base_url, ticket.location_id.qr_token)
        session_id, url = self._wave_checkout_session(
            ticket.payment_amount,
            ticket.currency_id.name or 'XOF',
            payment.client_ref,
            return_url,
            # Le compte marchand de l'établissement encaisse, pas celui de la
            # plateforme : sans cela sa clé API n'était jamais utilisée.
            company=ticket.company_id,
        )
        payment.provider_ref = self._wave_safe_ref(payment, session_id) or \
            payment.provider_ref
        ticket.sudo().payment_ref = session_id
        return url

    @api.model
    def _wave_handle_webhook(self, event):
        """Un paiement de ticket n'est confirmé que pour son montant.

        Le rapprochement et la confirmation sont ceux du socle ; on ne garde
        ici que ce qui est propre au ticket : Wave annonçant moins que le dû
        (100 F pour 5 000 F), le paiement n'est pas confirmé et le guichet en
        est averti. Un ticket annulé n'est pas ressuscité : le crochet
        ``_on_payment_paid`` le signale « à rembourser ».
        """
        status, transaction, client_ref = self._wave_event_data(event)
        if status in ('succeeded', 'success', 'paid'):
            payment = self._wave_find_payment(transaction, client_ref)
            if payment and payment.res_model == 'queue.ticket' \
                    and payment.state != 'paid':
                data = (event or {}).get('data') or event or {}
                amount = data.get('amount')
                if amount not in (None, ''):
                    try:
                        received = float(amount)
                    except (TypeError, ValueError):
                        received = None
                    if received is None or payment.currency_id.compare_amounts(
                            received, payment.amount) < 0:
                        _logger.warning(
                            "Webhook Wave : %s, montant reçu %s < dû %s",
                            payment.name, amount, payment.amount)
                        ticket = payment._document()
                        if ticket:
                            ticket.message_post(body=_(
                                "Wave annonce un paiement de %(recu)s pour "
                                "%(du)s dû : non confirmé, à vérifier au "
                                "guichet.", recu=amount,
                                du=ticket._amount_label()))
                        return True
        return super()._wave_handle_webhook(event)
