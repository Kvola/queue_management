# -*- coding: utf-8 -*-
"""Rate-limit PG multi-worker pour l'API mobile publique.

Les compteurs vivent dans PostgreSQL avec ``SELECT FOR UPDATE`` : deux workers
Odoo concurrents sont sérialisés sur la même ``key`` (un compteur in-memory
serait multiplié par le nombre de workers). Le verrou se libère à la fin de la
transaction HTTP. Pattern repris de ``association_management`` (éprouvé sur
l'API Coconut), embarqué ici pour que le module reste autonome.
"""
import json
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QueueRateLimit(models.Model):
    _name = 'queue.rate.limit'
    _description = "Rate-limit API (compteurs PG multi-worker)"
    _rec_name = 'key'

    key = fields.Char("Clé", required=True, index=True)
    events_json = fields.Text(
        "Événements (JSON)", default='[]',
        help="Horodatages ISO 8601 des hits récents dans la fenêtre.",
    )
    blocked_until = fields.Datetime(
        "Bloqué jusqu'à",
        help="Si défini et > now, toute demande est refusée.",
    )
    last_seen = fields.Datetime(
        "Dernier hit", default=fields.Datetime.now, index=True,
        help="Mis à jour à chaque check ; sert au cron de purge.",
    )

    _key_uniq = models.Constraint(
        'UNIQUE(key)',
        "La clé de rate-limit doit être unique.",
    )

    @api.model
    def check_and_record(self, key, max_requests, window_seconds, block_seconds):
        """Vérifie et enregistre un hit pour ``key``. Atomique multi-worker.

        :returns: ``(is_limited, seconds_remaining)``
        """
        cr = self.env.cr
        now = fields.Datetime.now()

        # Crée la row si absente (concurrent-safe via ON CONFLICT).
        cr.execute(
            """
            INSERT INTO queue_rate_limit
                (key, events_json, last_seen, create_uid, write_uid, create_date, write_date)
            VALUES (%s, '[]', %s, 1, 1, %s, %s)
            ON CONFLICT (key) DO NOTHING
            """,
            (key, now, now, now),
        )
        # Verrouille la row — sérialise les workers concurrents sur cette clé.
        cr.execute(
            "SELECT id, events_json, blocked_until FROM queue_rate_limit"
            " WHERE key = %s FOR UPDATE",
            (key,),
        )
        bucket_id, events_json, blocked_until = cr.fetchone()

        if blocked_until and blocked_until > now:
            cr.execute(
                "UPDATE queue_rate_limit SET last_seen=%s WHERE id=%s",
                (now, bucket_id),
            )
            return True, int((blocked_until - now).total_seconds())

        try:
            events = json.loads(events_json or '[]')
        except (ValueError, TypeError):
            events = []
        cutoff = now - timedelta(seconds=window_seconds)
        events = [
            ts for ts in events
            if self._parse_ts(ts) and self._parse_ts(ts) > cutoff
        ]

        if len(events) >= max_requests:
            cr.execute(
                "UPDATE queue_rate_limit"
                " SET events_json=%s, blocked_until=%s, last_seen=%s WHERE id=%s",
                (json.dumps(events), now + timedelta(seconds=block_seconds),
                 now, bucket_id),
            )
            _logger.info("rate-limit atteint pour %s (%s hits/%ss)",
                         key, max_requests, window_seconds)
            return True, block_seconds

        events.append(now.isoformat())
        cr.execute(
            "UPDATE queue_rate_limit"
            " SET events_json=%s, blocked_until=NULL, last_seen=%s WHERE id=%s",
            (json.dumps(events), now, bucket_id),
        )
        return False, 0

    @api.model
    def reset_key(self, key):
        """Réinitialise le bucket ``key`` (tests / déblocage admin)."""
        self.env.cr.execute("DELETE FROM queue_rate_limit WHERE key = %s", (key,))

    @api.model
    def _cron_cleanup_stale(self, days=1):
        """Purge les buckets non vus depuis ``days`` jour(s)."""
        cutoff = fields.Datetime.now() - timedelta(days=days)
        self.env.cr.execute(
            "DELETE FROM queue_rate_limit WHERE last_seen < %s", (cutoff,))
        n = self.env.cr.rowcount
        if n:
            _logger.info("rate-limit : %s bucket(s) obsolète(s) purgé(s)", n)
        return True

    @staticmethod
    def _parse_ts(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
