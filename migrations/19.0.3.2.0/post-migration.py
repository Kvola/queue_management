# -*- coding: utf-8 -*-
"""Les paiements des tickets entrent dans le socle ``queue.payment``.

Jusqu'ici l'état du paiement vivait sur le ticket seul. Désormais chaque
règlement est un ``queue.payment`` rattaché au ticket, et le ticket ne fait
que refléter ce que le socle décide. Les tickets qui ont déjà un paiement
engagé reçoivent donc le leur :

* « à valider » → paiement à valider, avec la preuve déclarée ;
* « payé » (et « remboursé ») → paiement réglé, daté et signé comme avant ;
* « en attente » AVEC une référence Wave → paiement en attente portant la
  session, pour qu'un webhook tardif retrouve encore son paiement.

La preuve n'est **pas recopiée** : sa pièce jointe est repointée vers le
paiement. Lecture en SQL : le champ ``payment_proof`` du ticket n'est plus
stocké, c'est désormais un reflet du paiement.

Idempotente (un ticket déjà rattaché est sauté) et jamais bloquante.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

_STATE = {'to_validate': 'to_validate', 'paid': 'paid', 'refunded': 'paid',
          'pending': 'pending'}


def migrate(cr, version):
    if not version:
        return
    try:
        with cr.savepoint():
            _adopt(api.Environment(cr, SUPERUSER_ID, {}))
    except Exception:  # noqa: BLE001 — la mise à jour passe avant la reprise
        _logger.exception("queue_management : reprise des paiements de "
                          "tickets dans le socle impossible.")


def _adopt(env):
    cr = env.cr
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'queue_ticket'
                     AND column_name = 'payment_proof_filename'""")
    filename_col = ", t.payment_proof_filename" if cr.fetchone() else ", NULL"
    cr.execute(f"""
        SELECT t.id, t.company_id, t.currency_id, t.partner_id,
               t.payment_amount, t.payment_state, t.payment_method,
               t.payment_ref, t.paid_at, t.payment_submitted_at,
               t.payment_validated_by {filename_col}
          FROM queue_ticket t
         WHERE t.payment_id IS NULL
           AND (t.payment_state IN ('to_validate', 'paid', 'refunded')
                OR (t.payment_state = 'pending'
                    AND COALESCE(t.payment_ref, '') <> ''))
    """)
    Payment = env['queue.payment'].sudo()
    count = 0
    for (ticket_id, company_id, currency_id, partner_id, amount, state,
         method, ref, paid_at, submitted_at, validated_by,
         filename) in cr.fetchall():
        ref = (ref or '').strip() or False
        if ref and Payment.search_count([('company_id', '=', company_id),
                                         ('provider_ref', '=', ref)]):
            ref = False  # déjà portée par un autre paiement : on n'invente rien
        payment = Payment.create({
            'company_id': company_id,
            'currency_id': currency_id or env.company.currency_id.id,
            'partner_id': partner_id or False,
            'amount': amount or 0.0,
            'method': method or 'counter',
            'state': _STATE[state],
            'provider_ref': ref,
            'res_model': 'queue.ticket',
            'res_id': ticket_id,
            'submitted_at': submitted_at,
            'paid_at': paid_at if state in ('paid', 'refunded') else False,
            'validated_by': validated_by if state in ('paid', 'refunded') else False,
            'proof_filename': filename,
        })
        cr.execute("""
            UPDATE ir_attachment
               SET res_model = 'queue.payment', res_field = 'proof',
                   res_id = %s
             WHERE res_model = 'queue.ticket' AND res_field = 'payment_proof'
               AND res_id = %s
        """, (payment.id, ticket_id))
        cr.execute("UPDATE queue_ticket SET payment_id = %s WHERE id = %s",
                   (payment.id, ticket_id))
        count += 1
    if count:
        _logger.info("queue_management : %s paiement(s) de ticket repris dans "
                     "le socle.", count)
