# -*- coding: utf-8 -*-
import json

from odoo import fields, http
from odoo.http import request

# Défense en profondeur des pages publiques (borne, affichage) : elles sont
# autonomes (styles/scripts inline, aucune ressource externe) — on interdit
# donc tout chargement externe et tout embedding en iframe.
PUBLIC_PAGE_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
    "frame-ancestors 'none'"
)
PUBLIC_PAGE_HEADERS = [
    ('Content-Security-Policy', PUBLIC_PAGE_CSP),
    ('X-Content-Type-Options', 'nosniff'),
    ('Referrer-Policy', 'no-referrer'),
]


def secure_public_page(response):
    """Pose les en-têtes de sécurité sur une réponse de page publique."""
    for key, value in PUBLIC_PAGE_HEADERS:
        response.headers[key] = value
    return response


class QueueDisplayController(http.Controller):
    """Écran d'affichage de salle d'attente — public, sans login.

    L'URL contient le jeton secret du site (le même que celui du QR affiché à
    l'entrée), ce qui évite d'énumérer les sites des autres établissements. Tout
    l'accès aux données passe par ``sudo()`` mais reste strictement borné au site
    désigné par le jeton (aucune fuite inter-établissement).
    """

    SERVED_STATES = ('called', 'serving')

    def _get_location(self, token):
        if not token:
            return request.env['queue.location']
        return request.env['queue.location'].sudo().search(
            [('qr_token', '=', token), ('active', '=', True)], limit=1)

    def _display_data(self, location):
        counters = location.counter_ids.filtered('active')
        now_serving = []
        for counter in counters:
            ticket = counter.current_ticket_id
            shown = ticket if ticket and ticket.state in self.SERVED_STATES else None
            now_serving.append({
                'counter': counter.name,
                'ticket': shown.name if shown else '',
                'service': shown.service_id.name if shown else '',
                # "called" = vient d'être appelé, pas encore démarré → à mettre
                # en avant (clignotement / son côté client).
                'called': bool(shown and shown.state == 'called'),
            })

        waiting = location.service_ids.mapped('ticket_ids').filtered(
            lambda t: t.state == 'waiting')
        upcoming = [
            {'ticket': t.name, 'service': t.service_id.name}
            for t in waiting.sorted(key=lambda t: t._scheduling_key())[:6]
        ]
        # Attente par service (petit récap sous les appels).
        services = [
            {'name': s.name, 'waiting': s.waiting_count}
            for s in location.service_ids.filtered('active')
            if s.waiting_count
        ]
        # Jeton de "génération d'appel" : change dès qu'un ticket est appelé
        # (called_at). L'écran s'en sert pour déclencher un bip une seule fois.
        called = now_serving and max(
            (c.current_ticket_id.called_at for c in counters
             if c.current_ticket_id and c.current_ticket_id.called_at),
            default=False)
        return {
            'location': location.name,
            'now_serving': now_serving,
            'upcoming': upcoming,
            'services': services,
            'call_token': fields.Datetime.to_string(called) if called else '',
        }

    @staticmethod
    def _app_qr_src():
        """Src de l'image QR « installez l'app », ou False si rien à servir."""
        Release = request.env['queue.app.release'].sudo()
        return Release._landing_available() and Release._qr_src(size=220)

    @http.route('/queue/display/<string:token>', type='http', auth='public', sitemap=False)
    def display(self, token, **kw):
        location = self._get_location(token)
        if not location:
            return request.not_found()
        return secure_public_page(request.render('queue_management.display_page', {
            'data': self._display_data(location),
            'app_qr': self._app_qr_src(),
        }))

    @http.route('/queue/display/<string:token>/data', type='http', auth='public', sitemap=False)
    def display_data(self, token, **kw):
        location = self._get_location(token)
        if not location:
            return request.not_found()
        return secure_public_page(request.make_response(
            json.dumps(self._display_data(location)),
            headers=[('Content-Type', 'application/json; charset=utf-8')],
        ))
