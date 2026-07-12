# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models.res_config_settings import int_param


@tagged('post_install', '-at_install')
class TestSettings(TransactionCase):
    """Les réglages produit (Paramètres → File d'attente) pilotent bien le
    comportement, avec les défauts historiques en fallback."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.location = cls.env['queue.location'].create({'name': 'Site Cfg'})
        cls.service = cls.env['queue.service'].create({
            'name': 'File Cfg', 'code': 'CFG', 'location_id': cls.location.id})

    def _set(self, key, value):
        self.env['ir.config_parameter'].sudo().set_param(key, value)

    def test_int_param_fallbacks(self):
        self.assertEqual(int_param(self.env, 'queue_management.absent', 7), 7)
        self._set('queue_management.absent', '')
        self.assertEqual(int_param(self.env, 'queue_management.absent', 7), 7)
        self._set('queue_management.absent', 'pas-un-nombre')
        self.assertEqual(int_param(self.env, 'queue_management.absent', 7), 7)
        self._set('queue_management.absent', '12')
        self.assertEqual(int_param(self.env, 'queue_management.absent', 7), 12)

    def test_settings_write_params(self):
        """La page Paramètres écrit bien les ir.config_parameter."""
        settings = self.env['res.config.settings'].create({
            'queue_max_active_tickets': 3,
            'queue_soon_threshold': 1,
            'queue_token_ttl_days': 30,
            'queue_no_show_delay_min': 15,
            'queue_app_store_url': 'https://play.example/app',
        })
        settings.execute()
        icp = self.env['ir.config_parameter'].sudo()
        self.assertEqual(icp.get_param('queue_management.max_active_tickets'), '3')
        self.assertEqual(icp.get_param('queue_management.soon_threshold'), '1')
        self.assertEqual(icp.get_param('queue_management.app_store_url'),
                         'https://play.example/app')

    def test_soon_threshold_param_honored(self):
        self._set('queue_management.soon_threshold', '1')
        t1 = self.env['queue.ticket'].create({'service_id': self.service.id})
        t2 = self.env['queue.ticket'].create({'service_id': self.service.id})
        self.service._notify_upcoming()
        self.assertTrue(t1.soon_notified)
        self.assertFalse(t2.soon_notified)

    def test_token_ttl_param_honored(self):
        self._set('queue_management.token_ttl_days', '7')
        customer = self.env['queue.customer'].create({'email': 'ttl@test.com'})
        customer.write({
            'otp_hash': customer._hash('123456'),
            'otp_expiry': fields.Datetime.now() + timedelta(minutes=5),
        })
        customer.verify_otp('123456')
        self.assertLessEqual(
            customer.token_expiry,
            fields.Datetime.now() + timedelta(days=7, minutes=1))

    def test_no_show_delay_param_honored(self):
        self._set('queue_management.no_show_delay_min', '5')
        overdue = self.env['queue.ticket'].create({
            'service_id': self.service.id, 'channel': 'appointment',
            'state': 'scheduled',
            'scheduled_time': fields.Datetime.now() - timedelta(minutes=10)})
        recent = self.env['queue.ticket'].create({
            'service_id': self.service.id, 'channel': 'appointment',
            'state': 'scheduled',
            'scheduled_time': fields.Datetime.now() - timedelta(minutes=2)})
        self.env['queue.ticket']._cron_expire_appointments()
        self.assertEqual(overdue.state, 'no_show')
        self.assertEqual(recent.state, 'scheduled')
