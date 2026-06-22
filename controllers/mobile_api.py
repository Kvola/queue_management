# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

from odoo import http, fields
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

# Anti-spam : un seul code toutes les 60 s par client.
_OTP_RESEND_SECONDS = 60


class QueueMobileApi(http.Controller):
    """API REST de l'application mobile client (Phase 2).

    Parcours : scanner le QR du site → voir les files → se connecter par email
    (OTP) → prendre un ticket → suivre sa position (polling). Toutes les routes
    sont publiques ; l'identité du client est portée par ``auth_token``.
    """

    # --- Helpers -------------------------------------------------------------

    @staticmethod
    def _ok(**data):
        return dict(status='ok', **data)

    @staticmethod
    def _err(message):
        return {'status': 'error', 'message': message}

    def _get_customer(self, kw):
        token = kw.get('auth_token')
        if not token:
            return False
        customer = request.env['queue.customer'].sudo().search(
            [('token', '=', token), ('active', '=', True)], limit=1)
        return customer or False

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
        }

    # --- Authentification par email (OTP) ------------------------------------

    @http.route('/api/queue/auth/request_otp', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def request_otp(self, **kw):
        email = (kw.get('email') or '').strip().lower()
        if not email or '@' not in email:
            return self._err("Adresse email invalide.")
        Customer = request.env['queue.customer'].sudo()
        customer = Customer.search([('email', '=', email)], limit=1)
        if not customer:
            customer = Customer.create({'email': email, 'name': kw.get('name')})
        if customer.last_otp_sent and (
                fields.Datetime.now() - customer.last_otp_sent
                < timedelta(seconds=_OTP_RESEND_SECONDS)):
            return self._err("Un code vient d'être envoyé. Patientez un instant.")
        customer.send_otp()
        return self._ok(message="Un code de connexion a été envoyé par email.")

    @http.route('/api/queue/auth/verify_otp', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def verify_otp(self, **kw):
        email = (kw.get('email') or '').strip().lower()
        code = (kw.get('otp') or '').strip()
        customer = request.env['queue.customer'].sudo().search(
            [('email', '=', email)], limit=1)
        if not customer:
            return self._err("Demandez d'abord un code de connexion.")
        token = customer.verify_otp(code)
        if not token:
            return self._err("Code invalide ou expiré.")
        return self._ok(
            auth_token=token,
            customer={'id': customer.id, 'email': customer.email, 'name': customer.name or ''},
        )

    # --- Découverte d'un site via son QR -------------------------------------

    @http.route('/api/queue/site', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def site(self, **kw):
        location = request.env['queue.location'].sudo().search(
            [('qr_token', '=', kw.get('qr_token')), ('active', '=', True)], limit=1)
        if not location:
            return self._err("Site introuvable.")
        services = [
            {'id': s.id, 'name': s.name, 'code': s.code, 'waiting': s.waiting_count,
             'appointment': s.appointment_enabled}
            for s in location.service_ids.filtered('active')
        ]
        return self._ok(
            site={'id': location.id, 'name': location.name, 'city': location.city or ''},
            services=services,
        )

    # --- Tickets -------------------------------------------------------------

    @http.route('/api/queue/ticket/create', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def ticket_create(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err("Non authentifié.")
        service = request.env['queue.service'].sudo().browse(
            int(kw.get('service_id') or 0))
        if not service.exists() or not service.active:
            return self._err("File invalide.")
        # Un seul ticket actif par client et par file.
        existing = request.env['queue.ticket'].sudo().search([
            ('partner_id', '=', customer.partner_id.id),
            ('service_id', '=', service.id),
            ('state', 'in', ('waiting', 'called', 'serving')),
        ], limit=1)
        if existing:
            return self._ok(ticket=self._ticket_data(existing),
                            message="Vous avez déjà un ticket pour cette file.")
        ticket = request.env['queue.ticket'].sudo().create({
            'service_id': service.id,
            'partner_id': customer.partner_id.id,
            'channel': 'mobile',
        })
        return self._ok(ticket=self._ticket_data(ticket))

    @http.route('/api/queue/ticket/status', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def ticket_status(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err("Non authentifié.")
        ticket = request.env['queue.ticket'].sudo().browse(int(kw.get('ticket_id') or 0))
        if not ticket.exists() or ticket.partner_id != customer.partner_id:
            return self._err("Ticket introuvable.")
        return self._ok(ticket=self._ticket_data(ticket))

    @http.route('/api/queue/ticket/cancel', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def ticket_cancel(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err("Non authentifié.")
        ticket = request.env['queue.ticket'].sudo().browse(int(kw.get('ticket_id') or 0))
        if not ticket.exists() or ticket.partner_id != customer.partner_id:
            return self._err("Ticket introuvable.")
        if ticket.state not in ('scheduled', 'waiting', 'called'):
            return self._err("Ce ticket ne peut plus être annulé.")
        ticket.action_cancel()
        return self._ok(ticket=self._ticket_data(ticket))

    @http.route('/api/queue/tickets', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def my_tickets(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err("Non authentifié.")
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
            return self._err("Cette file ne propose pas de rendez-vous.")
        try:
            day = datetime.strptime(kw.get('date') or '', '%Y-%m-%d').date()
        except ValueError:
            return self._err("Date invalide (attendu AAAA-MM-JJ).")
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
            return self._err("Non authentifié.")
        service = request.env['queue.service'].sudo().browse(
            int(kw.get('service_id') or 0))
        if not service.exists():
            return self._err("File invalide.")
        try:
            slot_dt = datetime.strptime(kw.get('slot') or '', '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return self._err("Créneau invalide.")
        try:
            ticket = service._book_appointment(customer.partner_id, slot_dt)
        except UserError as exc:
            return self._err(exc.args[0] if exc.args else "Réservation impossible.")
        return self._ok(ticket=self._ticket_data(ticket))

    @http.route('/api/queue/ticket/checkin', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def ticket_checkin(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err("Non authentifié.")
        ticket = request.env['queue.ticket'].sudo().browse(
            int(kw.get('ticket_id') or 0))
        if not ticket.exists() or ticket.partner_id != customer.partner_id:
            return self._err("Rendez-vous introuvable.")
        try:
            ticket.action_check_in()
        except UserError as exc:
            return self._err(exc.args[0] if exc.args else "Enregistrement impossible.")
        return self._ok(ticket=self._ticket_data(ticket))

    # --- Notifications push (prépare la Phase 3) -----------------------------

    @http.route('/api/queue/fcm/register', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def fcm_register(self, **kw):
        customer = self._get_customer(kw)
        if not customer:
            return self._err("Non authentifié.")
        customer.fcm_token = (kw.get('fcm_token') or '').strip()
        return self._ok()
