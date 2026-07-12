# -*- coding: utf-8 -*-
import json

from odoo import http
from odoo.http import request

from .main import secure_public_page


class QueueKioskController(http.Controller):
    """Borne tactile à l'entrée d'un site — page web publique, sans login.

    Le client touche une file → un ticket anonyme (canal ``kiosk``, sans
    ``partner_id``) est créé et son numéro s'affiche. L'URL est protégée par le
    jeton du site ; l'accès aux données passe par ``sudo()`` mais reste borné au
    site désigné par le jeton.
    """

    def _get_location(self, token):
        if not token:
            return request.env['queue.location']
        return request.env['queue.location'].sudo().search(
            [('qr_token', '=', token), ('active', '=', True)], limit=1)

    def _services(self, location):
        return [
            {'id': s.id, 'name': s.name, 'code': s.code, 'waiting': s.waiting_count}
            for s in location.service_ids.filtered('active')
        ]

    @http.route('/queue/kiosk/<string:token>', type='http', auth='public', sitemap=False)
    def kiosk(self, token, **kw):
        location = self._get_location(token)
        if not location:
            return request.not_found()
        return secure_public_page(request.render('queue_management.kiosk_page', {
            'token': token,
            'site_name': location.name,
            'services': self._services(location),
        }))

    @http.route('/queue/kiosk/<string:token>/ticket', type='http', auth='public',
                methods=['POST'], csrf=False, sitemap=False)
    def kiosk_ticket(self, token, **kw):
        location = self._get_location(token)
        if not location:
            return request.not_found()
        try:
            service_id = int(kw.get('service_id') or 0)
        except (TypeError, ValueError):
            service_id = 0
        # La file doit appartenir à CE site (anti-falsification du service_id).
        service = location.service_ids.filtered(
            lambda s: s.id == service_id and s.active)
        if not service:
            return secure_public_page(request.make_response(
                json.dumps({'status': 'error', 'message': 'File invalide.'}),
                headers=[('Content-Type', 'application/json; charset=utf-8')]))
        ticket = request.env['queue.ticket'].sudo().create({
            'service_id': service.id,
            'channel': 'kiosk',
        })
        payload = {
            'status': 'ok',
            'ticket': {
                'name': ticket.name,
                'service': service.name,
                'position': ticket.position,
            },
        }
        return secure_public_page(request.make_response(
            json.dumps(payload),
            headers=[('Content-Type', 'application/json; charset=utf-8')]))
