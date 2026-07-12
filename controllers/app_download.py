# -*- coding: utf-8 -*-
"""Distribution publique de l'app mobile.

* ``GET /queue/app`` : page d'installation (version publiée, bouton, SHA-256,
  instructions). C'est l'URL encodée dans les QR — si le paramètre système
  ``queue_management.app_store_url`` est défini (passage au Play Store), la
  page redirige vers le store sans qu'aucun QR imprimé ne devienne obsolète.
* ``GET /queue/app/download`` : binaire APK de la version publiée,
  rate-limité par IP.
"""
import base64
import logging

from odoo import http
from odoo.http import request

from .main import secure_public_page

_logger = logging.getLogger(__name__)

# Téléchargements APK par IP : large pour un hall d'attente derrière un NAT,
# bloquant pour un aspirateur de bande passante (l'APK pèse des dizaines de Mo).
_RL_APK_DOWNLOAD = dict(max_requests=15, window_seconds=60, block_seconds=120)


class QueueAppDownloadController(http.Controller):

    @http.route('/queue/app', type='http', auth='public',
                methods=['GET'], sitemap=False)
    def landing(self, **kw):
        Release = request.env['queue.app.release'].sudo()
        store_url = Release._store_url()
        if store_url:
            return request.redirect(store_url, code=302, local=False)
        release = Release._get_published()
        if not release or not release.apk_file:
            return request.not_found()
        return secure_public_page(request.render(
            'queue_management.app_landing_page', {'release': release}))

    @http.route('/queue/app/download', type='http', auth='public',
                methods=['GET'], sitemap=False)
    def download(self, **kw):
        ip = (request.httprequest.headers.get('X-Forwarded-For', '')
              .split(',')[0].strip() or request.httprequest.remote_addr
              or 'unknown')
        limited, retry_after = request.env['queue.rate.limit'].sudo(
        ).check_and_record(f"queue_apk_dl:{ip}", **_RL_APK_DOWNLOAD)
        if limited:
            return request.make_response(
                "Trop de téléchargements depuis cette adresse. Réessayez plus tard.",
                headers=[('Content-Type', 'text/plain; charset=utf-8'),
                         ('Retry-After', str(retry_after))],
                status=429)

        release = request.env['queue.app.release'].sudo()._get_published()
        if not release or not release.apk_file:
            return request.not_found()
        try:
            data = base64.b64decode(release.apk_file)
        except Exception:
            _logger.exception("APK release %s : binaire illisible", release.id)
            return request.not_found()
        release.increment_download()
        filename = (release.apk_file_name
                    or 'queue_mobile-v%s.apk' % (release.version or '0'))
        return request.make_response(data, headers=[
            ('Content-Type', 'application/vnd.android.package-archive'),
            ('Content-Disposition',
             'attachment; filename="%s"' % filename.replace('"', '')),
            ('Content-Length', str(len(data))),
            ('X-Content-Type-Options', 'nosniff'),
            ('Cache-Control', 'public, max-age=3600'),
        ])
