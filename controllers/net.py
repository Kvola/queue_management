# -*- coding: utf-8 -*-
"""Adresse IP du client, pour les limites d'appels.

Le premier élément de ``X-Forwarded-For`` est écrit par le client lui-même :
s'en servir comme clé de limite permettait de la contourner en changeant
d'en-tête à chaque requête — codes de connexion envoyés sans fin, borne
inondée de tickets.

Derrière le proxy de production (``--proxy-mode``), Odoo a déjà placé dans
``remote_addr`` l'adresse vue par le proxy. Reste le cas où Odoo n'a pas
appliqué cette correction (en-tête ``X-Forwarded-Host`` absent) : l'adresse
directe est alors celle du proxy, privée ou locale. On ne lit l'en-tête que
dans ce cas, et son **dernier** élément — celui qu'a ajouté notre proxy, que
le client ne peut pas choisir.
"""
import ipaddress

from odoo.http import request


def _is_internal(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def client_ip():
    httprequest = request.httprequest
    direct = httprequest.remote_addr or ''
    if _is_internal(direct):
        forwarded = [part.strip() for part in httprequest.headers.get(
            'X-Forwarded-For', '').split(',') if part.strip()]
        if forwarded:
            return forwarded[-1]
    return direct or 'unknown'
