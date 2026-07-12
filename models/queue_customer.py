# -*- coding: utf-8 -*-
import hashlib
import logging
import secrets
import string
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import email_normalize

_logger = logging.getLogger(__name__)


class QueueCustomer(models.Model):
    """Client de l'application mobile, identifié par son email.

    L'email EST le compte : connexion par code à usage unique (OTP) envoyé par
    email, sans mot de passe. Le ``res.partner`` miroir n'est créé qu'à la
    première connexion réussie (pas à la demande de code), pour qu'un flood
    d'emails ne pollue pas l'annuaire des partenaires.
    """

    _name = 'queue.customer'
    _description = "Client mobile (file d'attente)"
    _order = 'create_date desc'

    OTP_TTL_MINUTES = 10
    OTP_MAX_ATTEMPTS = 5
    # Durée de vie d'une session mobile. L'app se reconnecte par OTP à
    # l'expiration ; évite qu'un jeton fuité soit valable à vie.
    TOKEN_TTL_DAYS = 90

    name = fields.Char("Nom")
    email = fields.Char("Email", required=True, index=True)
    partner_id = fields.Many2one('res.partner', string="Partenaire", ondelete='set null')
    active = fields.Boolean("Actif", default=True)

    # Session — jetons secrets : illisibles hors administrateur système
    # (les agents n'en ont pas besoin ; l'API mobile y accède en sudo).
    # ``token`` stocke le HASH SHA-256 du jeton (jamais le jeton en clair) :
    # un dump de la base ne donne aucune session rejouable.
    token = fields.Char("Jeton de session (haché)", readonly=True, copy=False,
                        index=True, groups='base.group_system')
    token_expiry = fields.Datetime("Expiration de session", readonly=True,
                                   copy=False, groups='base.group_system')
    fcm_token = fields.Char("Jeton FCM", readonly=True, copy=False,
                            groups='base.group_system',
                            help="Pour les notifications push.")

    # OTP (stocké haché)
    otp_hash = fields.Char(readonly=True, copy=False)
    otp_expiry = fields.Datetime(readonly=True, copy=False)
    otp_attempts = fields.Integer(default=0, copy=False)
    last_otp_sent = fields.Datetime(readonly=True, copy=False)

    _email_uniq = models.Constraint(
        'UNIQUE(email)',
        "Un client existe déjà avec cet email.",
    )

    @api.model
    def _normalize_email(self, email):
        """Normalise (et valide) un email. Lève si l'adresse est invalide.

        ``email_normalize`` refuse aussi les valeurs à en-têtes injectés
        (retours à la ligne, adresses multiples).
        """
        normalized = email_normalize(email)
        if not normalized:
            raise ValidationError(_("Adresse email invalide : %s", email or ''))
        return normalized

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('email'):
                vals['email'] = self._normalize_email(vals['email'])
        return super().create(vals_list)

    def write(self, vals):
        # Même normalisation qu'à la création : une correction manuelle en
        # backoffice ne doit pas casser la connexion (recherches en minuscules).
        if vals.get('email'):
            vals['email'] = self._normalize_email(vals['email'])
        return super().write(vals)

    def _ensure_partner(self):
        """Crée le ``res.partner`` miroir s'il manque (idempotent)."""
        for customer in self:
            if not customer.partner_id:
                customer.partner_id = self.env['res.partner'].sudo().create({
                    'name': customer.name or customer.email,
                    'email': customer.email,
                })
        return self.mapped('partner_id')

    @staticmethod
    def _hash(code):
        return hashlib.sha256((code or '').encode()).hexdigest()

    def send_otp(self):
        """Génère un code à 6 chiffres, le stocke haché et l'envoie par email.

        Lève ``MailDeliveryException`` si le SMTP échoue : l'appelant doit
        pouvoir dire au client que le code n'est PAS parti (plutôt que de le
        laisser attendre un email fantôme). Dans ce cas l'OTP et l'anti-spam
        sont réarmés pour permettre une nouvelle tentative immédiate.
        """
        self.ensure_one()
        code = ''.join(secrets.choice(string.digits) for _ in range(6))
        self.write({
            'otp_hash': self._hash(code),
            'otp_expiry': fields.Datetime.now() + timedelta(minutes=self.OTP_TTL_MINUTES),
            'otp_attempts': 0,
            'last_otp_sent': fields.Datetime.now(),
        })
        try:
            self._send_otp_email(code)
        except Exception:
            self.write({'otp_hash': False, 'otp_expiry': False,
                        'last_otp_sent': False})
            raise

    def _otp_email_from(self):
        """Expéditeur des emails OTP, déterministe.

        Sans ``email_from`` explicite, Odoo exige le couple
        ``mail.catchall.domain`` + ``mail.default.from`` et échoue sinon
        (constaté sur base neuve). On force donc : paramètre
        ``mail.default.from`` s'il existe, sinon l'email de la société.
        """
        icp = self.env['ir.config_parameter'].sudo()
        return (icp.get_param('mail.default.from')
                or self.env.company.sudo().email_formatted
                or False)

    def _send_otp_email(self, code):
        self.ensure_one()
        body = (
            "<p>Bonjour,</p>"
            "<p>Votre code de connexion à la file d'attente est :</p>"
            "<p style=\"font-size:28px;font-weight:bold;letter-spacing:4px\">%s</p>"
            "<p>Ce code expire dans %d minutes. Si vous n'êtes pas à l'origine de "
            "cette demande, ignorez cet email.</p>"
        ) % (code, self.OTP_TTL_MINUTES)
        mail = self.env['mail.mail'].sudo().create({
            'subject': "Votre code de connexion",
            'email_from': self._otp_email_from(),
            'email_to': self.email,
            'body_html': body,
            'auto_delete': True,
        })
        # raise_exception : l'échec SMTP doit remonter tout de suite, pas être
        # avalé (sinon l'API répond « code envoyé » à tort).
        mail.send(raise_exception=True)

    def verify_otp(self, code):
        """Valide un code OTP. Retourne le jeton de session en clair, ou ``False``.

        Le jeton n'existe qu'ici en clair : la base ne stocke que son hash.
        C'est aussi le moment où le ``res.partner`` miroir est créé (première
        connexion réussie).
        """
        self.ensure_one()
        if not self.otp_hash or not self.otp_expiry:
            return False
        if fields.Datetime.now() > self.otp_expiry:
            return False
        if self.otp_attempts >= self.OTP_MAX_ATTEMPTS:
            return False
        if self._hash(code) != self.otp_hash:
            self.otp_attempts += 1
            return False
        from .res_config_settings import int_param
        ttl_days = int_param(self.env, 'queue_management.token_ttl_days',
                             self.TOKEN_TTL_DAYS)
        token = secrets.token_hex(32)
        self.write({
            'token': self._hash(token),
            'token_expiry': fields.Datetime.now() + timedelta(days=max(ttl_days, 1)),
            'otp_hash': False,
            'otp_expiry': False,
            'otp_attempts': 0,
        })
        self._ensure_partner()
        return token

    def _revoke_session(self):
        """Déconnexion côté serveur : invalide le jeton ET le canal push.

        Effacer ``fcm_token`` est essentiel : sinon le prochain utilisateur du
        même téléphone recevrait les notifications de tickets de l'ancien.
        """
        self.sudo().write({
            'token': False,
            'token_expiry': False,
            'fcm_token': False,
        })

    def _register_fcm(self, fcm_token):
        """Attache le jeton FCM de l'appareil à CE client, et à lui seul.

        Un jeton FCM identifie un appareil : s'il restait attaché à un autre
        compte (connexion précédente sur le même téléphone), l'appareil
        recevrait les notifications de ce compte-là.
        """
        self.ensure_one()
        fcm_token = (fcm_token or '').strip()
        sudo_self = self.sudo()
        if fcm_token:
            others = sudo_self.search([
                ('fcm_token', '=', fcm_token), ('id', '!=', self.id)])
            others.write({'fcm_token': False})
        sudo_self.fcm_token = fcm_token or False

    @api.model
    def _cron_purge_unverified(self, days=30):
        """Purge les comptes jamais connectés (demande d'OTP sans suite).

        Hygiène anti-flood : un compte sans partenaire miroir et sans session
        n'a jamais passé ``verify_otp`` ; au-delà de ``days`` jours, c'est du
        déchet (faute de frappe ou abus).
        """
        cutoff = fields.Datetime.now() - timedelta(days=days)
        stale = self.with_context(active_test=False).search([
            ('partner_id', '=', False),
            ('token', '=', False),
            ('create_date', '<', cutoff),
        ])
        if stale:
            _logger.info("queue_management : purge de %d compte(s) jamais vérifié(s)",
                         len(stale))
            stale.unlink()
        return True

    def _push(self, title, body, data=None):
        """Envoie une notification push FCM au client (best-effort).

        Réutilise l'initialisation Firebase de ``push_notification_hub`` mais en
        ciblant directement le ``fcm_token`` du client (qui n'est pas un
        ``res.users``, donc hors API ``send(user_ids=...)`` du hub). Ne lève
        jamais : si FCM n'est pas configuré ou échoue, on logge et on continue.
        """
        self.ensure_one()
        # fcm_token est restreint à base.group_system → lecture en sudo.
        fcm_token = self.sudo().fcm_token
        if not fcm_token:
            return False
        if 'push.notification' not in self.env:
            _logger.info("push_notification_hub absent : push « %s » non envoyé", title)
            return False
        Push = self.env['push.notification'].sudo()
        messaging = Push._get_fcm_messaging()
        if messaging is None:
            _logger.info("FCM non configuré : push « %s » non envoyé à %s",
                         title, self.email)
            return False
        payload = {str(k): str(v) for k, v in (data or {}).items() if v is not None}
        try:
            Push._send_one(messaging, fcm_token, title, body, payload)
            return True
        except Exception as exc:  # noqa: BLE001 — best-effort, jamais bloquant
            _logger.warning("queue_management : échec push à %s : %s", self.email, exc)
            return False
