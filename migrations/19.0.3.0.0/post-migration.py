# -*- coding: utf-8 -*-
"""Reprend les versions de ``queue.app.release`` dans le catalogue commun.

Le modèle ``queue.app.release`` disparaît : Kvla File se distribue désormais
par ``mobile_app_release``. Ses versions déjà téléversées deviennent des
versions de ``mobile.app`` « kvla-file » — la publiée reste publiée, les
autres passent à l'historique.

**Le fichier n'est pas recopié.** La pièce jointe existante est repointée vers
la nouvelle version : un APK pèse des dizaines de mégaoctets, et le recopier
voudrait dire le charger en mémoire, sur une base de production, au milieu
d'une mise à jour. Ce repointage doit avoir lieu ICI, en post-migration : la
table de l'ancien modèle existe encore, et ce n'est qu'en fin de mise à jour
qu'Odoo efface ce qu'il ne connaît plus.

Lecture en SQL : la classe Python de l'ancien modèle n'existe plus.

Idempotente (un numéro déjà présent est sauté) et jamais bloquante : une
exception ici arrêterait toute la mise à jour du module.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT to_regclass('queue_app_release')")
    if not cr.fetchone()[0]:
        return
    try:
        with cr.savepoint():
            _adopt(api.Environment(cr, SUPERUSER_ID, {}))
    except Exception:  # noqa: BLE001 — la mise à jour passe avant la reprise
        _logger.exception(
            "queue_management : reprise des APK dans le catalogue impossible ; "
            "republiez la version depuis Configuration → App mobile.")


def _adopt(env):
    cr = env.cr
    app = env.ref('queue_management.mobile_app_kvla_file',
                  raise_if_not_found=False)
    if not app:
        _logger.warning("queue_management : fiche Kvla File absente, reprise "
                        "des APK impossible.")
        return
    Release = env['mobile.app.release'].sudo()
    cr.execute("""
        SELECT r.id, r.version, r.build_number, r.is_active, r.release_notes,
               r.released_date, r.apk_file_name, r.download_count, a.id
          FROM queue_app_release r
          JOIN ir_attachment a
            ON a.res_model = 'queue.app.release' AND a.res_field = 'apk_file'
           AND a.res_id = r.id
      ORDER BY r.released_date, r.id
    """)
    for (legacy_id, number, build, active, notes, released, filename,
         downloads, attachment_id) in cr.fetchall():
        # Le catalogue range les versions comme pubspec.yaml : « 1.4.0+6 ».
        version = '%s+%s' % ((number or '0').strip(), build or 0)
        if Release.search_count([('app_id', '=', app.id),
                                 ('version', '=', version)]):
            continue
        release = Release.create({
            'app_id': app.id,
            'version': version,
            'apk_filename': filename or 'kvla-file-%s.apk' % version,
            'release_notes': notes or False,
            'download_count': downloads or 0,
        })
        cr.execute("""
            UPDATE ir_attachment
               SET res_model = 'mobile.app.release', res_id = %s,
                   public = FALSE
             WHERE id = %s
        """, (release.id, attachment_id))
        release.invalidate_recordset(['apk_file'])
        try:
            with cr.savepoint():
                release._sync_file_info()
        except Exception:  # noqa: BLE001 — fichier douteux : on le garde, dépublié
            _logger.warning("queue_management : APK %s illisible, repris "
                            "sans être publié.", version)
            active = False
        release.write({
            'state': 'published' if active else 'archived',
            'publish_date': released,
        })
        _logger.info("queue_management : version %s reprise dans le "
                     "catalogue (%s).", version,
                     'publiée' if active else 'historique')
