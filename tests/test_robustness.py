# -*- coding: utf-8 -*-
"""Robustesse métier (phase 5 de l'audit du 2026-09-29).

Fuseau du site, jeton de borne distinct de l'affiche, ordre de file
déterministe, positions calculées une fois par file.
"""
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSiteTimezone(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Douala : UTC+1 toute l'année.
        cls.location = cls.env['queue.location'].create({
            'name': 'Hôpital de Douala', 'tz': 'Africa/Douala'})
        cls.service = cls.env['queue.service'].create({
            'name': 'Cardiologie', 'code': 'CAR', 'location_id': cls.location.id,
            'appointment_enabled': True, 'slot_duration': 30, 'slot_capacity': 1})
        for day in range(7):
            cls.env['queue.opening.hour'].create({
                'service_id': cls.service.id, 'dayofweek': str(day),
                'hour_from': 8.0, 'hour_to': 9.0})

    def test_opening_hours_are_local_hours(self):
        """« Ouvert à 8 h » veut dire 8 h à Douala, soit 7 h UTC en base."""
        day = date.today() + timedelta(days=1)
        slots = self.service._slots_for_date(day)
        self.assertEqual([s for s, _ in slots],
                         [datetime.combine(day, time(7, 0)),
                          datetime.combine(day, time(7, 30))])
        self.assertEqual(self.service._utc_to_local(slots[0][0]).time(),
                         time(8, 0))

    def test_booking_a_local_slot_uses_it(self):
        day = date.today() + timedelta(days=1)
        slot = self.service._slots_for_date(day)[0][0]
        partner = self.env['res.partner'].create({'name': 'Patient'})
        ticket = self.service._book_appointment(partner, slot)
        self.assertEqual(ticket.scheduled_time, slot)
        self.assertEqual(dict(self.service._slots_for_date(day))[slot], 0)

    def test_numbering_restarts_at_local_midnight(self):
        """23 h 30 UTC le 29 = 0 h 30 le 30 à Douala : nouveau jour, n° 1."""
        self.service.write({'last_number': 41,
                            'last_number_date': date(2026, 9, 29)})
        with patch.object(fields.Datetime, 'now',
                          return_value=datetime(2026, 9, 29, 23, 30)):
            self.assertEqual(self.service._next_number(), 'CAR-001')
            self.assertEqual(self.service.last_number_date, date(2026, 9, 30))

    def test_default_timezone_is_abidjan(self):
        site = self.env['queue.location'].create({'name': 'Mairie'})
        self.assertEqual(site.tz, 'Africa/Abidjan')


@tagged('post_install', '-at_install')
class TestQueueOrder(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.location = cls.env['queue.location'].create({'name': 'Ordre'})
        cls.service = cls.env['queue.service'].create({
            'name': 'Accueil', 'code': 'ACC', 'location_id': cls.location.id})

    def test_same_second_arrivals_are_served_in_creation_order(self):
        """Un afflux à la borne : même seconde, l'ordre ne doit pas dépendre
        de la lecture en base."""
        stamp = fields.Datetime.now()
        tickets = self.env['queue.ticket'].create([
            {'service_id': self.service.id, 'created_at': stamp}
            for _i in range(4)])
        self.assertEqual(self.service._get_ordered_waiting(), tickets)

    def test_positions_of_a_whole_queue_in_one_read(self):
        tickets = self.env['queue.ticket'].create([
            {'service_id': self.service.id} for _i in range(5)])
        tickets.invalidate_recordset(['position'])
        self.assertEqual(tickets.mapped('position'), [1, 2, 3, 4, 5])

    def test_closed_history_is_not_read_to_order_the_queue(self):
        """La file se lit sur les seuls tickets en attente."""
        done = self.env['queue.ticket'].create([
            {'service_id': self.service.id} for _i in range(3)])
        done.write({'state': 'cancelled'})
        waiting = self.env['queue.ticket'].create({'service_id': self.service.id})
        self.assertEqual(self.service._get_ordered_waiting(), waiting)
        self.assertEqual(self.service.waiting_count, 1)
        self.assertEqual(self.service.ticket_count, 4)


@tagged('post_install', '-at_install')
class TestKioskToken(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.location = cls.env['queue.location'].create({'name': 'Hall borne'})
        cls.service = cls.env['queue.service'].create({
            'name': 'Guichet', 'code': 'G', 'location_id': cls.location.id})

    def test_the_entrance_qr_does_not_open_the_kiosk(self):
        """Une photo de l'affiche d'entrée ne donne plus accès à la borne."""
        qr = self.location.qr_token
        self.assertEqual(self.url_open('/queue/kiosk/%s' % qr).status_code, 404)
        resp = self.url_open('/queue/kiosk/%s/ticket' % qr,
                             data={'service_id': self.service.id})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(self.env['queue.ticket'].search_count(
            [('service_id', '=', self.service.id)]))

    def test_the_kiosk_opens_with_its_own_token(self):
        kiosk = self.location.kiosk_token
        self.assertTrue(kiosk)
        self.assertNotEqual(kiosk, self.location.qr_token)
        self.assertEqual(self.url_open('/queue/kiosk/%s' % kiosk).status_code, 200)
        action = self.location.action_open_kiosk()
        self.assertTrue(action['url'].endswith(kiosk))

    def test_each_site_has_its_own_kiosk_token(self):
        other = self.env['queue.location'].create({'name': 'Autre hall'})
        self.assertNotEqual(other.kiosk_token, self.location.kiosk_token)

    def test_regenerating_closes_the_old_address(self):
        old = self.location.kiosk_token
        self.location.action_regenerate_kiosk_token()
        self.assertNotEqual(self.location.kiosk_token, old)
        self.assertEqual(self.url_open('/queue/kiosk/%s' % old).status_code, 404)
