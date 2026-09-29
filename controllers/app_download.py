# -*- coding: utf-8 -*-
"""Anciennes adresses de l'app mobile, tenues en vie.

L'app se distribue désormais par le catalogue commun
(``mobile_app_release``) : page ``/apps/kvla-file``, téléchargement, guide et
version navigateur. Mais ``/queue/app`` est encodée dans les QR déjà imprimés
et affichés dans les salles d'attente : elle ne doit jamais mourir.

* ``GET /queue/app`` redirige vers le store si le paramètre
  ``queue_management.app_store_url`` est réglé (passage au Play Store), sinon
  vers la page du catalogue.
* ``GET /queue/app/download`` redirige vers le téléchargement du catalogue,
  qui sert le fichier sans le charger en mémoire et tient le compteur.

Le QR de la borne et de l'écran de salle continue d'encoder ``/queue/app`` :
c'est la seule adresse qui suit un passage au store sans réimpression.
"""
from odoo import http
from odoo.http import request

APP_SLUG = 'kvla-file'


def store_url(env):
    """URL de store (Play Store…) : si définie, ``/queue/app`` y mène."""
    return (env['ir.config_parameter'].sudo()
            .get_param('queue_management.app_store_url') or '').strip()


def app_available(env):
    """L'app a-t-elle quelque chose à offrir ? (pilote les QR publics)

    Un APK publié ou une version navigateur suffit ; sans l'un ni l'autre, un
    QR mènerait à une page vide.
    """
    if store_url(env):
        return True
    app = env.ref('queue_management.mobile_app_kvla_file',
                  raise_if_not_found=False)
    return bool(app and app.sudo().active and app.sudo().is_distributable())


class QueueAppDownloadController(http.Controller):

    @http.route('/queue/app', type='http', auth='public',
                methods=['GET'], sitemap=False)
    def landing(self, **kw):
        url = store_url(request.env)
        if url:
            return request.redirect(url, code=302, local=False)
        return request.redirect('/apps/%s' % APP_SLUG, code=302)

    @http.route('/queue/app/download', type='http', auth='public',
                methods=['GET'], sitemap=False)
    def download(self, **kw):
        return request.redirect('/apps/%s/download' % APP_SLUG, code=302)
