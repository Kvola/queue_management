# -*- coding: utf-8 -*-
"""Donne à chaque site existant son propre jeton de borne.

Le champ ``kiosk_token`` a une valeur par défaut calculée, mais Odoo, en
créant la colonne sur une table déjà remplie, évalue ce défaut UNE fois et le
recopie sur toutes les lignes : tous les sites partageraient la même adresse
de borne, et la contrainte d'unicité ferait échouer la mise à jour. On crée
donc la colonne ici, avant Odoo, et on tire un jeton par site.

Les bornes déjà installées doivent être rouvertes avec la nouvelle adresse
(bouton « Borne tactile » de la fiche du site) : l'ancienne était celle du
QR d'entrée, précisément ce qu'on ferme.
"""
import secrets


def migrate(cr, version):
    if not version:
        return
    cr.execute("ALTER TABLE queue_location ADD COLUMN IF NOT EXISTS kiosk_token varchar")
    cr.execute("ALTER TABLE queue_location ADD COLUMN IF NOT EXISTS tz varchar")
    cr.execute("UPDATE queue_location SET tz = 'Africa/Abidjan' WHERE tz IS NULL")
    cr.execute("SELECT id FROM queue_location WHERE kiosk_token IS NULL")
    for (location_id,) in cr.fetchall():
        cr.execute("UPDATE queue_location SET kiosk_token = %s WHERE id = %s",
                   (secrets.token_urlsafe(16), location_id))
