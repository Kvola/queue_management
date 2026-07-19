# -*- coding: utf-8 -*-
import base64
import json
import logging
from datetime import datetime, timedelta

from odoo import _, http, fields
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import email_normalize

_logger = logging.getLogger(__name__)

# Anti-spam : un seul code toutes les 60 s par client.
_OTP_RESEND_SECONDS = 60

# Rate-limits par IP (multi-worker, backés PG — cf. queue.rate.limit).
# Volontairement généreux : un site peut mettre tout un hall derrière un même
# NAT/Wi-Fi. L'objectif est de stopper le flood automatisé, pas les humains.
_RL_OTP_REQUEST = dict(max_requests=30, window_seconds=3600, block_seconds=600)
_RL_OTP_VERIFY = dict(max_requests=60, window_seconds=300, block_seconds=300)

# Nombre total de tickets actifs (file + RDV à venir) qu'un même client peut
# détenir, tous établissements confondus. Personne ne fait la queue à 5
# guichets à la fois : au-delà, c'est un abus.
_MAX_ACTIVE_TICKETS = 5


class QueueMobileApi(http.Controller):
    """API REST de l'application mobile client (Phase 2).

    Parcours : scanner le QR du site → voir les files → se connecter par email
    (OTP) → prendre un ticket → suivre sa position (polling). Toutes les routes
    sont publiques ; l'identité du client est portée par ``auth_token`` (dont
    seul le hash est stocké en base).
    """

    # --- Helpers -------------------------------------------------------------

    @staticmethod
    def _ok(**data):
        # ``success`` double ``status`` : c'est la clé qu'attend le client
        # Dart partagé (ebng_odoo_client). Les deux formes coexistent le
        # temps que toutes les apps migrent.
        return dict(status='ok', success=True, **data)

    @staticmethod
    def _err(message, code=None):
        """Erreur métier. ``code`` machine-lisible optionnel : l'app ne doit
        pas dépendre du libellé français (ex. ``auth_required`` → déconnexion
        automatique côté client)."""
        res = {
            'status': 'error', 'message': message,
            'success': False,
            'error': {'message': message, 'code': code},
        }
        if code:
            res['code'] = code
        return res

    @staticmethod
    def _client_ip():
        """IP du client, en tenant compte d'un éventuel reverse proxy."""
        headers = request.httprequest.headers
        forwarded = headers.get('X-Forwarded-For', '')
        if forwarded:
            return forwarded.split(',')[0].strip()
        real_ip = headers.get('X-Real-IP', '')
        if real_ip:
            return real_ip.strip()
        return request.httprequest.remote_addr or 'unknown'

    def _rate_limited(self, scope, max_requests, window_seconds, block_seconds):
        """Renvoie une réponse d'erreur si l'IP appelante dépasse la limite."""
        limited, retry_after = request.env['queue.rate.limit'].sudo().check_and_record(
            f"{scope}:{self._client_ip()}",
            max_requests, window_seconds, block_seconds,
        )
        if limited:
            return self._err(_(
                "Trop de tentatives. Réessayez dans %s minute(s).",
                max(retry_after // 60, 1)))
        return None

    def _get_customer(self, kw):
        token = kw.get('auth_token')
        if not token:
            # Client Dart partagé : jeton porté par l'en-tête Authorization.
            header = request.httprequest.headers.get('Authorization') or ''
            if header.lower().startswith('bearer '):
                token = header[7:].strip()
        if not token:
            return False
        Customer = request.env['queue.customer'].sudo()
        # Seul le hash du jeton est stocké : on compare hash à hash.
        customer = Customer.search(
            [('token', '=', Customer._hash(token)), ('active', '=', True)],
            limit=1)
        if not customer:
            return False
        if customer.token_expiry and fields.Datetime.now() > customer.token_expiry:
            return False  # session expirée : l'app doit se reconnecter par OTP
        return customer

    @staticmethod
    def _ticket_data(ticket):
        return {
            'id': ticket.id,
            'name': ticket.name if ticket.name != '/' else '',
            'state': ticket.state,
            'position': ticket.position,
            'service': ticket.service_id.name,
            'site': ticket.location_id.name,
            'counter': ticket.counter_id.name or '',
            'channel': ticket.channel,
            'scheduled_time': fields.Datetime.to_string(ticket.scheduled_time)
            if ticket.scheduled_time else '',
            'eta_minutes': ticket.eta_minutes,
            'payment_state': ticket.payment_state,
            'payment_amount': ticket.payment_amount,
            'currency': ticket.currency_id.symbol or ticket.currency_id.name or '',
            'payment_method': ticket.payment_method or '',
            'wave_direct': ticket.env['queue.wave.mixin'].sudo()._wave_api_configured(),
            'wave_merchant': ticket.env['queue.wave.mixin'].sudo()._wave_merchant_label(),
        }

    # --- Authentification par email (OTP) ------------------------------------

    @http.route('/api/queue/auth/request_otp', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def request_otp(self, **kw):
        limited = self._rate_limited('queue_otp_req', **_RL_OTP_REQUEST)
        if limited:
            return limited
        email = email_normalize(kw.get('email') or '')
        if not email:
            return self._err(_("Adresse email invalide."))
        Customer = request.env['queue.customer'].sudo()
        customer = Customer.search([('email', '=', email)], limit=1)
        if not customer:
            # Ne crée que la fiche client (PAS de res.partner : il n'est créé
            # qu'à la première connexion réussie, cf. queue.customer).
            customer = Customer.create({'email': email, 'name': kw.get('name')})
        if customer.last_otp_sent and (
                fields.Datetime.now() - customer.last_otp_sent
                < timedelta(seconds=_OTP_RESEND_SECONDS)):
            return self._err(_("Un code vient d'être envoyé. Patientez un instant."))
        try:
            customer.send_otp()
        except Exception as exc:  # noqa: BLE001 — tout échec = code non délivré
            _logger.warning("queue_management : échec d'envoi OTP à %s : %s",
                            email, exc)
            return self._err(
                _("L'email n'a pas pu être envoyé. Réessayez dans un instant."))
        return self._ok(message=_("Un code de connexion a été envoyé par email."))

    @http.route('/api/queue/auth/verify_otp', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def verify_otp(self, **kw):
        limited = self._rate_limited('queue_otp_verif', **_RL_OTP_VERIFY)
        if limited:
            return limited
        email = email_normalize(kw.get('email') or '')
        code = (kw.get('otp') or '').strip()
        customer = request.env['queue.customer'].sudo().search(
            [('email', '=', email)], limit=1)
        if not customer:
            return self._err(_("Demandez d'abord un code de connexion."))
        token = customer.verify_otp(code)
        if not token:
            return self._err(_("Code invalide ou expiré."))
        return self._ok(
            auth_token=token,
            customer={'id': customer.id, 'email': customer.email, 'name': customer.name or ''},
        )

    @http.route('/api/queue/auth/logout', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def logout(self, **kw):
        """Révocation serveur de la session (jeton + canal push).

        Toujours ``ok`` : un jeton déjà invalide est un logout réussi.
        """
        customer = self._get_customer(kw)
        if customer:
            customer._revoke_session()
        return self._ok()

    # --- Découverte d'un site via son QR -------------------------------------

    @http.route('/api/queue/site', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def site(self, **kw):
        location = request.env['queue.location'].sudo().search(
            [('qr_token', '=', kw.get('qr_token')), ('active', '=', True)], limit=1)
        if not location:
            return self._err(_("Site introuvable."))
        services = [
            {'id': s.id, 'name': s.name, 'code': s.code, 'waiting': s.waiting_count,
             'appointment': s.appointment_enabled, 'remote': s._remote_available(),
             'payment_required': s.payment_required,
             'price': s.price, 'currency': s.currency_id.symbol or s.currency_id.name or ''}
            for s in location.service_ids.filtered('active')
        ]
        wave = request.env['queue.wave.mixin'].sudo()
        return self._ok(
            # qr_token renvoyé en écho : l'app le conserve pour prouver, à la
            # prise de ticket, qu'elle a bien scanné le QR de ce site.
            site={'id': location.id, 'name': location.name,
                  'city': location.city or '', 'qr_token': location.qr_token},
            services=services,
            payment={
                'wave_direct': wave._wave_api_configured(),
                'wave_merchant': wave._wave_merchant_label(),
            },
        )

    @staticmethod
    def _active_quota_reached(partner):
        """Garde anti-flood : plafonne les tickets actifs d'un même client.

        Plafond configurable (Paramètres → File d'attente), défaut 5.
        """
        from odoo.addons.queue_management.models.res_config_settings import int_param
        limit = max(int_param(request.env, 'queue_management.max_active_tickets',
                              _MAX_ACTIVE_TICKETS), 1)
        count = request.env['queue.ticket'].sudo().search_count([
            ('partner_id', '=', partner.id),
            ('state', 'in', ('scheduled', 'waiting', 'called', 'serving')),
        ])
        return count >= limit

    # --- Tickets -------------------------------------------------------------

    @http.route('/api/queue/ticket/create', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def ticket_create(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err(_("Non authentifié."), code='auth_required')
        service = request.env['queue.service'].sudo().browse(
            int(kw.get('service_id') or 0))
        if not service.exists() or not service.active:
            return self._err(_("Service invalide."))
        # Le jeton du QR reste exigé : il prouve que le client a scanné le
        # site au moins une fois (anti-énumération du service_id). Le mode
        # « à distance » (jeton mémorisé, client pas sur place) n'est permis
        # que si la file l'autorise, et se distingue dans les stats.
        if kw.get('qr_token') != service.location_id.qr_token:
            return self._err(_("Scannez le QR code du site pour prendre un ticket."))
        remote = bool(kw.get('remote'))
        if remote and not service._remote_available():
            return self._err(_(
                "Ce service n'accepte pas les tickets à distance. "
                "Rendez-vous sur place pour prendre votre ticket."))
        # Filet de sécurité : un compte créé en backoffice peut ne pas encore
        # avoir de partenaire miroir (créé normalement au premier verify_otp).
        customer._ensure_partner()
        # Un seul ticket actif par client et par file.
        existing = request.env['queue.ticket'].sudo().search([
            ('partner_id', '=', customer.partner_id.id),
            ('service_id', '=', service.id),
            ('state', 'in', ('waiting', 'called', 'serving')),
        ], limit=1)
        if existing:
            return self._ok(ticket=self._ticket_data(existing),
                            message=_("Vous avez déjà un ticket pour ce service."))
        if self._active_quota_reached(customer.partner_id):
            return self._err(_(
                "Vous avez trop de tickets en cours. "
                "Terminez ou annulez-en avant d'en prendre un autre."))
        ticket = request.env['queue.ticket'].sudo().create({
            'service_id': service.id,
            'partner_id': customer.partner_id.id,
            'channel': 'remote' if remote else 'mobile',
        })
        return self._ok(ticket=self._ticket_data(ticket))

    @http.route('/api/queue/ticket/status', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def ticket_status(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err(_("Non authentifié."), code='auth_required')
        ticket = request.env['queue.ticket'].sudo().browse(int(kw.get('ticket_id') or 0))
        if not ticket.exists() or ticket.partner_id != customer.partner_id:
            return self._err(_("Ticket introuvable."))
        return self._ok(ticket=self._ticket_data(ticket))

    @http.route('/api/queue/ticket/cancel', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def ticket_cancel(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err(_("Non authentifié."), code='auth_required')
        ticket = request.env['queue.ticket'].sudo().browse(int(kw.get('ticket_id') or 0))
        if not ticket.exists() or ticket.partner_id != customer.partner_id:
            return self._err(_("Ticket introuvable."))
        if ticket.state not in ('scheduled', 'waiting', 'called'):
            return self._err(_("Ce ticket ne peut plus être annulé."))
        ticket.action_cancel()
        return self._ok(ticket=self._ticket_data(ticket))

    @http.route('/api/queue/tickets', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def my_tickets(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err(_("Non authentifié."), code='auth_required')
        tickets = request.env['queue.ticket'].sudo().search([
            ('partner_id', '=', customer.partner_id.id),
            ('state', 'in', ('scheduled', 'waiting', 'called', 'serving')),
        ])
        return self._ok(tickets=[self._ticket_data(t) for t in tickets])

    # --- Rendez-vous ---------------------------------------------------------

    @http.route('/api/queue/slots', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def slots(self, **kw):
        service = request.env['queue.service'].sudo().browse(
            int(kw.get('service_id') or 0))
        if not service.exists() or not service.appointment_enabled:
            return self._err(_("Ce service ne propose pas de rendez-vous."))
        try:
            day = datetime.strptime(kw.get('date') or '', '%Y-%m-%d').date()
        except ValueError:
            return self._err(_("Date invalide (attendu AAAA-MM-JJ)."))
        now = fields.Datetime.now()
        slots = []
        for slot_dt, available in service._slots_for_date(day):
            if slot_dt <= now:
                continue  # on ne propose pas un créneau déjà passé
            slots.append({
                'time': fields.Datetime.to_string(slot_dt),
                'label': slot_dt.strftime('%H:%M'),
                'available': available,
            })
        return self._ok(date=kw.get('date'), slots=slots)

    @http.route('/api/queue/appointment/book', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def appointment_book(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err(_("Non authentifié."), code='auth_required')
        service = request.env['queue.service'].sudo().browse(
            int(kw.get('service_id') or 0))
        if not service.exists():
            return self._err(_("Service invalide."))
        try:
            slot_dt = datetime.strptime(kw.get('slot') or '', '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return self._err(_("Créneau invalide."))
        customer._ensure_partner()
        if self._active_quota_reached(customer.partner_id):
            return self._err(_(
                "Vous avez trop de tickets ou rendez-vous en cours. "
                "Annulez-en avant d'en réserver un autre."))
        try:
            ticket = service._book_appointment(customer.partner_id, slot_dt)
        except UserError as exc:
            return self._err(exc.args[0] if exc.args else _("Réservation impossible."))
        return self._ok(ticket=self._ticket_data(ticket))

    @http.route('/api/queue/ticket/checkin', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def ticket_checkin(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err(_("Non authentifié."), code='auth_required')
        ticket = request.env['queue.ticket'].sudo().browse(
            int(kw.get('ticket_id') or 0))
        if not ticket.exists() or ticket.partner_id != customer.partner_id:
            return self._err(_("Rendez-vous introuvable."))
        try:
            ticket.action_check_in()
        except UserError as exc:
            return self._err(exc.args[0] if exc.args else _("Enregistrement impossible."))
        return self._ok(ticket=self._ticket_data(ticket))

    @http.route('/api/queue/ticket/pay', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def ticket_pay(self, **kw):
        """Le client déclare/initie un paiement (3 méthodes).

        - method='wave'   : si l'API Wave est configurée → paiement DIRECT
          (renvoie ``payment_url`` ; Wave confirmera par webhook). Sinon →
          Wave Marchand : ticket « à valider » + numéro marchand renvoyé.
        - method='counter': « je paierai au guichet » → « à valider ».
        - method='proof'  : preuve jointe (base64) → « à valider ».

        Toutes les voies « à valider » attendent la confirmation d'un agent au
        guichet ; seule l'API Wave court-circuite cette étape.
        """
        customer = self._get_customer(kw)
        if not customer:
            return self._err(_("Non authentifié."), code='auth_required')
        ticket = request.env['queue.ticket'].sudo().browse(
            int(kw.get('ticket_id') or 0))
        if not ticket.exists() or ticket.partner_id != customer.partner_id:
            return self._err(_("Ticket introuvable."))
        if ticket.payment_state in ('paid', 'to_validate'):
            return self._ok(ticket=self._ticket_data(ticket))
        if ticket.payment_state != 'pending':
            return self._err(_("Ce ticket n'attend pas de paiement."))

        method = kw.get('method') or 'wave'
        wave = request.env['queue.wave.mixin'].sudo()

        if method == 'wave' and wave._wave_api_configured():
            # Voie directe (API Checkout) : session + webhook, sans validation.
            from odoo.addons.queue_payment.models.queue_wave import WaveError
            try:
                url = wave._wave_create_checkout(ticket)
                return self._ok(ticket=self._ticket_data(ticket),
                                payment_url=url)
            except WaveError:
                pass  # repli sur le lien de paiement ci-dessous

        proof_b64 = kw.get('proof')
        proof = False
        if method == 'proof':
            if not proof_b64:
                return self._err(_("Joignez une preuve de paiement."))
            try:
                base64.b64decode(proof_b64)  # validation
                proof = proof_b64
            except Exception:
                return self._err(_("Preuve illisible."))
        try:
            ticket._submit_payment(method, ref=kw.get('ref'),
                                   proof=proof,
                                   proof_filename=kw.get('proof_filename'))
        except UserError as exc:
            return self._err(exc.args[0] if exc.args else _("Paiement impossible."))
        extra = {}
        if method == 'wave':
            # Lien Wave (compagnie ou défaut) avec le montant → l'app l'ouvre.
            # Le paiement reste « à valider » (un lien ne confirme pas seul).
            extra['payment_url'] = wave._wave_payment_url(ticket)
            extra['merchant'] = wave._wave_merchant_label()
        return self._ok(ticket=self._ticket_data(ticket), **extra)

    @http.route('/api/queue/wave/webhook', type='http', auth='public',
                methods=['POST'], csrf=False)
    def wave_webhook(self, **kw):
        """Notification de paiement Wave (voie directe). Signature vérifiée."""
        raw = request.httprequest.get_data()
        sig = request.httprequest.headers.get('Wave-Signature') \
            or request.httprequest.headers.get('X-Wave-Signature')
        wave = request.env['queue.wave.mixin'].sudo()
        if not wave._wave_verify_signature(raw, sig):
            return request.make_response('invalid signature', status=403)
        try:
            event = json.loads(raw or b'{}')
        except ValueError:
            return request.make_response('bad payload', status=400)
        wave._wave_handle_webhook(event)
        return request.make_response('ok')

    # --- Notifications push ---------------------------------------------------

    @http.route('/api/queue/fcm/register', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def fcm_register(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err(_("Non authentifié."), code='auth_required')
        customer._register_fcm(kw.get('fcm_token'))
        return self._ok()
