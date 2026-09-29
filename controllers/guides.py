# -*- coding: utf-8 -*-
"""Guides du personnel, derrière la connexion.

Les guides de l'agent, du responsable et de l'administrateur étaient servis
depuis ``static/`` : n'importe qui, sans compte, pouvait lire comment
l'opérateur configure Wave ou suspend un établissement. Ils vivent désormais
hors de ``static/`` et passent par une seule route, qui exige une connexion et
le groupe du rôle concerné.

Le guide du **visiteur**, lui, est public : c'est celui du catalogue
(``/apps/kvla-file/guide``).

Chaque module de la file d'attente inscrit ses guides dans ``STAFF_GUIDES``
(``register_staff_guide``) ; la route, elle, n'est écrite qu'une fois.

* ``/queue/guide/<nom>``      → page HTML
* ``/queue/guide/<nom>.pdf``  → version imprimable
"""
from odoo import http
from odoo.http import Stream, request

# nom public → (module, fichier sans extension, groupe requis)
STAFF_GUIDES = {}

# La page est autonome (styles en ligne produits par pandoc) : sans cette
# politique, Odoo sert un fichier avec `default-src 'none'` et la page
# s'affiche sans aucune mise en forme.
_GUIDE_CSP = ("default-src 'none'; style-src 'unsafe-inline'; "
              "img-src 'self' data:; base-uri 'none'; frame-ancestors 'self'")


def register_staff_guide(name, module, filename, group):
    STAFF_GUIDES[name] = (module, filename, group)


register_staff_guide('agent', 'queue_management', 'guide_agent',
                     'queue_management.group_queue_agent')
register_staff_guide('responsable', 'queue_management', 'guide_responsable',
                     'queue_management.group_queue_manager')
register_staff_guide('administrateur', 'queue_management', 'guide_administrateur',
                     'base.group_system')


class QueueStaffGuides(http.Controller):

    @http.route('/queue/guide/<string:name>', type='http', auth='user',
                methods=['GET'], sitemap=False)
    def staff_guide(self, name, **kw):
        pdf = name.endswith('.pdf')
        entry = STAFF_GUIDES.get(name[:-4] if pdf else name)
        # Guide inconnu ou rôle insuffisant : même réponse. Dire « interdit »
        # confirmerait qu'un guide existe à cette adresse.
        if not entry or not request.env.user.has_group(entry[2]):
            return request.not_found()
        module, filename, _group = entry
        path = ('%s/docs/pdf/%s.pdf' if pdf else '%s/docs/html/%s.html') % (
            module, filename)
        try:
            stream = Stream.from_path(path)
        except FileNotFoundError:
            return request.not_found()
        response = stream.get_response(as_attachment=False)
        if not pdf:
            response.headers['Content-Security-Policy'] = _GUIDE_CSP
        return response
