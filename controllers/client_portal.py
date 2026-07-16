# -*- coding: utf-8 -*-
"""Portail client (navigateur) — l'app mobile en version web.

Pour les usagers sans application Android : toutes les fonctions clientes dans
un simple navigateur. Le portail ne fait **aucune** logique métier propre : il
appelle les mêmes endpoints ``/api/queue/*`` que l'app (découverte du site,
connexion OTP, prise de ticket, suivi, annulation, rendez-vous, paiement). Le
push est remplacé par du sondage, la session est gardée en ``localStorage``.

Entrée : le QR d'entrée du site encode ``…/queue/u/<qr_token>`` — un scan avec
l'appareil photo ouvre directement ce portail pour le bon site. Installable
(PWA) : manifeste dynamique + service worker.
"""
import json

from odoo import http
from odoo.http import request

# Pages du portail : autonomes (styles/scripts inline) mais qui appellent notre
# propre API (connect-src 'self') et s'installent en PWA (manifest/worker).
_PORTAL_CSP = (
    "default-src 'self'; style-src 'unsafe-inline' 'self'; "
    "script-src 'unsafe-inline' 'self'; connect-src 'self'; "
    "img-src 'self' data:; manifest-src 'self'; worker-src 'self'; "
    "base-uri 'none'; frame-ancestors 'none'"
)


def _secure_portal(response):
    response.headers['Content-Security-Policy'] = _PORTAL_CSP
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


class QueueClientPortal(http.Controller):

    @http.route(['/queue/u', '/queue/u/<string:token>'],
                type='http', auth='public', sitemap=False)
    def client_portal(self, token='', **kw):
        return _secure_portal(request.render(
            'queue_management.client_portal_page', {'token': token or ''}))

    @http.route('/queue/u/<string:token>/manifest.webmanifest',
                type='http', auth='public', sitemap=False)
    def manifest(self, token, **kw):
        data = {
            'name': "File d'attente",
            'short_name': "File",
            'start_url': '/queue/u/%s' % token,
            'scope': '/queue/u/',
            'display': 'standalone',
            'background_color': '#0f172a',
            'theme_color': '#2563eb',
            'lang': 'fr',
            'icons': [
                {'src': '/queue_management/static/pwa/icon-192.png',
                 'sizes': '192x192', 'type': 'image/png',
                 'purpose': 'any maskable'},
                {'src': '/queue_management/static/pwa/icon-512.png',
                 'sizes': '512x512', 'type': 'image/png',
                 'purpose': 'any maskable'},
            ],
        }
        return request.make_response(json.dumps(data), headers=[
            ('Content-Type', 'application/manifest+json; charset=utf-8')])

    @http.route('/queue/sw.js', type='http', auth='public', sitemap=False)
    def service_worker(self):
        sw = (
            "self.addEventListener('install', function(e){ self.skipWaiting(); });\n"
            "self.addEventListener('activate', function(e){ e.waitUntil(self.clients.claim()); });\n"
            "self.addEventListener('fetch', function(e){\n"
            "  if (e.request.mode === 'navigate') {\n"
            "    e.respondWith(fetch(e.request).catch(function(){\n"
            "      return new Response('<h1>Hors ligne</h1><p>Reconnectez-vous pour suivre votre file.</p>',"
            " {headers:{'Content-Type':'text/html; charset=utf-8'}});\n"
            "    }));\n"
            "  }\n"
            "});\n"
        )
        return request.make_response(sw, headers=[
            ('Content-Type', 'text/javascript; charset=utf-8'),
            # Autorise le scope /queue/u/ pour un worker servi depuis /queue/.
            ('Service-Worker-Allowed', '/queue/'),
        ])
