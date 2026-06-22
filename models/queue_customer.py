# -*- coding: utf-8 -*-
import hashlib
import logging
import secrets
import string
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QueueCustomer(models.Model):
    """Client de l'application mobile, identifié par son email.

    L'email EST le compte : connexion par code à usage unique (OTP) envoyé par
    email, sans mot de passe. Un ``res.partner`` est créé en miroir pour que les
    tickets restent rattachés à un partenaire Odoo standard.
    """

    _name = 'queue.customer'
    _description = "Client mobile (file d'attente)"
    _order = 'create_date desc'

    OTP_TTL_MINUTES = 10
    OTP_MAX_ATTEMPTS = 5

    name = fields.Char("Nom")
    email = fields.Char("Email", required=True, index=True)
    partner_id = fields.Many2one('res.partner', string="Partenaire", ondelete='set null')
    active = fields.Boolean("Actif", default=True)

    # Session
    token = fields.Char("Jeton de session", readonly=True, copy=False, index=True)
    fcm_token = fields.Char("Jeton FCM", readonly=True, copy=False,
                            help="Pour les notifications push (Phase 3).")

    # OTP (stocké haché)
    otp_hash = fields.Char(readonly=True, copy=False)
    otp_expiry = fields.Datetime(readonly=True, copy=False)
    otp_attempts = fields.Integer(default=0, copy=False)
    last_otp_sent = fields.Datetime(readonly=True, copy=False)

    _email_uniq = models.Constraint(
        'UNIQUE(email)',
        "Un client existe déjà avec cet email.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('email'):
                vals['email'] = vals['email'].strip().lower()
        customers = super().create(vals_list)
        customers._ensure_partner()
        return customers

    def _ensure_partner(self):
        for customer in self:
            if not customer.partner_id:
                customer.partner_id = self.env['res.partner'].sudo().create({
                    'name': customer.name or customer.email,
                    'email': customer.email,
                })

    @staticmethod
    def _hash(code):
        return hashlib.sha256((code or '').encode()).hexdigest()

    def send_otp(self):
        """Génère un code à 6 chiffres, le stocke haché et l'envoie par email."""
        self.ensure_one()
        code = ''.join(secrets.choice(string.digits) for _ in range(6))
        self.write({
            'otp_hash': self._hash(code),
            'otp_expiry': fields.Datetime.now() + timedelta(minutes=self.OTP_TTL_MINUTES),
            'otp_attempts': 0,
            'last_otp_sent': fields.Datetime.now(),
        })
        self._send_otp_email(code)

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
            'email_to': self.email,
            'body_html': body,
            'auto_delete': True,
        })
        # force_send : on veut l'échec SMTP tout de suite, pas un envoi différé.
        mail.send(raise_exception=False)

    def verify_otp(self, code):
        """Valide un code OTP. Retourne un jeton de session, ou ``False``."""
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
        token = secrets.token_hex(32)
        self.write({
            'token': token,
            'otp_hash': False,
            'otp_expiry': False,
            'otp_attempts': 0,
        })
        return token

    def _push(self, title, body, data=None):
        """Envoie une notification push FCM au client (best-effort).

        Réutilise l'initialisation Firebase de ``push_notification_hub`` mais en
        ciblant directement le ``fcm_token`` du client (qui n'est pas un
        ``res.users``, donc hors API ``send(user_ids=...)`` du hub). Ne lève
        jamais : si FCM n'est pas configuré ou échoue, on logge et on continue.
        """
        self.ensure_one()
        if not self.fcm_token:
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
            Push._send_one(messaging, self.fcm_token, title, body, payload)
            return True
        except Exception as exc:  # noqa: BLE001 — best-effort, jamais bloquant
            _logger.warning("queue_management : échec push à %s : %s", self.email, exc)
            return False
