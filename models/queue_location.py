# -*- coding: utf-8 -*-
import secrets
from datetime import datetime, time

from odoo import _, api, fields, models


class QueueLocation(models.Model):
    """Site physique d'un établissement (un hôpital peut avoir plusieurs sites).

    C'est le point de rattachement du client : un QR code est affiché à l'entrée
    de chaque site ; en le scannant, l'application mobile sait à quel site (et
    donc à quelle société) rattacher le client, sans aucune saisie.
    """

    _name = 'queue.location'
    _description = "Site (file d'attente)"
    _order = 'company_id, name'

    name = fields.Char("Nom du site", required=True, translate=True)
    company_id = fields.Many2one(
        'res.company', string="Établissement", required=True, index=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean("Actif", default=True)

    street = fields.Char("Adresse")
    city = fields.Char("Ville")

    # Jeton secret encodé dans le QR code affiché à l'entrée. On stocke le jeton
    # (pas l'établissement en clair) pour éviter qu'une URL devinable ne rattache
    # un client au mauvais site.
    qr_token = fields.Char(
        "Jeton QR", copy=False, readonly=True, index=True,
        default=lambda self: secrets.token_urlsafe(16),
        help="Identifiant encodé dans le QR code du site. Régénérable.",
    )
    qr_html = fields.Html(
        "QR d'entrée", compute='_compute_qr_html',
        sanitize=False, sanitize_attributes=False,
        help="À imprimer et afficher à l'entrée du site. Les clients le "
             "scannent DEPUIS l'application (Prendre un ticket → scan) pour "
             "voir les files de ce site.",
    )

    service_ids = fields.One2many('queue.service', 'location_id', string="Files")
    counter_ids = fields.One2many('queue.counter', 'location_id', string="Guichets")
    service_count = fields.Integer("Nb de files", compute='_compute_counts')
    counter_count = fields.Integer("Nb de guichets", compute='_compute_counts')

    _qr_token_uniq = models.Constraint(
        'UNIQUE(qr_token)',
        "Le jeton QR doit être unique.",
    )

    @api.depends('service_ids', 'counter_ids')
    def _compute_counts(self):
        for location in self:
            location.service_count = len(location.service_ids)
            location.counter_count = len(location.counter_ids)

    @api.depends('qr_token', 'name')
    def _compute_qr_html(self):
        # Le QR encode le jeton brut : c'est ce que l'app attend (elle accepte
        # aussi une URL finissant par le jeton, cf. ScanScreen._extractToken).
        for location in self:
            if not location.qr_token:
                location.qr_html = False
                continue
            src = ('/report/barcode/?barcode_type=QR&value=%s&width=320&height=320'
                   % location.qr_token)
            location.qr_html = (
                '<div style="display:inline-block;text-align:center;padding:12px;'
                'background:#fff;border:1px solid #dee2e6;border-radius:8px;">'
                '<img src="%s" alt="QR du site" '
                'style="width:280px;height:280px;display:block;"/>'
                '<div style="margin-top:6px;font-weight:bold;">%s</div>'
                '</div>'
            ) % (src, location.name or '')

    def action_regenerate_qr_token(self):
        """Invalide le QR précédent (en cas de fuite ou d'affiche remplacée)."""
        for location in self:
            location.qr_token = secrets.token_urlsafe(16)
        return True

    def action_open_display(self):
        """Ouvre l'écran d'affichage public du site (à mettre en plein écran)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/queue/display/{self.qr_token}',
            'target': 'new',
        }

    def action_open_kiosk(self):
        """Ouvre la borne tactile du site (à mettre en plein écran à l'entrée)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/queue/kiosk/{self.qr_token}',
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Tableau de bord temps réel (client action Owl)
    # ------------------------------------------------------------------

    @api.model
    def get_dashboard_data(self, location_id=None):
        """Photographie « maintenant » d'un site, pour le tableau de bord.

        Appelée SANS sudo : les record rules multi-société s'appliquent, un
        responsable ne peut superviser que ses établissements. Re-sondée
        toutes les quelques secondes par le composant Owl → rester léger.
        """
        locations = self.search([])
        location = (locations.filtered(lambda l: l.id == location_id)
                    or locations[:1])
        result = {
            'locations': [{'id': l.id, 'name': l.display_name} for l in locations],
            'location_id': location.id if location else False,
            'now': fields.Datetime.to_string(fields.Datetime.now()),
        }
        if not location:
            return result

        Ticket = self.env['queue.ticket']
        today_start = datetime.combine(fields.Date.context_today(self), time.min)
        day_tickets = Ticket.search([
            ('location_id', '=', location.id),
            ('created_at', '>=', today_start),
        ])
        done = day_tickets.filtered(lambda t: t.state == 'done')
        no_show = day_tickets.filtered(lambda t: t.state == 'no_show')
        waits = [t.wait_real_minutes for t in done if t.wait_real_minutes > 0]
        closed_for_rate = len(done) + len(no_show)

        services = []
        for service in location.service_ids.filtered('active'):
            head = service._get_next_waiting()
            services.append({
                'id': service.id,
                'name': service.name,
                'code': service.code,
                'waiting': service.waiting_count,
                'next_number': head.name if head else '',
                'eta_next': head.eta_minutes if head else 0,
                'appointment': service.appointment_enabled,
            })

        counters = []
        for counter in location.counter_ids.filtered('active'):
            ticket = counter.current_ticket_id
            busy = counter.state == 'busy'
            counters.append({
                'id': counter.id,
                'name': counter.name,
                'busy': busy,
                'agent': counter.agent_id.name or '',
                'ticket': ticket.name if busy else '',
                'ticket_state': ticket.state if busy else '',
                'service': ticket.service_id.name if busy else '',
                # Nombre en attente sur les files desservies par CE guichet :
                # pilote le bouton « Appeler le suivant » du tableau de bord.
                'waiting': counter.waiting_count,
            })

        result.update({
            'kpis': {
                'waiting': sum(s['waiting'] for s in services),
                'done_today': len(done),
                'avg_wait_today': round(sum(waits) / len(waits), 1) if waits else 0.0,
                'no_show_rate': round(100.0 * len(no_show) / closed_for_rate, 1)
                if closed_for_rate else 0.0,
            },
            'services': services,
            'counters': counters,
        })
        return result
