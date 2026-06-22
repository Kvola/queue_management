# -*- coding: utf-8 -*-
import json

from odoo import http
from odoo.http import request


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
        return {
            'location': location.name,
            'now_serving': now_serving,
            'upcoming': upcoming,
        }

    @http.route('/queue/display/<string:token>', type='http', auth='public', sitemap=False)
    def display(self, token, **kw):
        location = self._get_location(token)
        if not location:
            return request.not_found()
        return request.render('queue_management.display_page', {
            'data': self._display_data(location),
        })

    @http.route('/queue/display/<string:token>/data', type='http', auth='public', sitemap=False)
    def display_data(self, token, **kw):
        location = self._get_location(token)
        if not location:
            return request.not_found()
        return request.make_response(
            json.dumps(self._display_data(location)),
            headers=[('Content-Type', 'application/json; charset=utf-8')],
        )
