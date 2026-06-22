# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestQueue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': "Test Hôpital"})
        cls.location = cls.env['queue.location'].create({
            'name': "Site test",
            'company_id': cls.company.id,
        })
        cls.service = cls.env['queue.service'].create({
            'name': "Cardio",
            'code': "car",
            'location_id': cls.location.id,
        })
        cls.counter = cls.env['queue.counter'].create({
            'name': "Guichet 1",
            'location_id': cls.location.id,
            'service_ids': [(6, 0, cls.service.ids)],
        })

    def _new_ticket(self, priority='0', channel='mobile', scheduled_time=False):
        return self.env['queue.ticket'].create({
            'service_id': self.service.id,
            'priority': priority,
            'channel': channel,
            'scheduled_time': scheduled_time,
        })

    def test_numbering_daily(self):
        """Le numéro reprend le préfixe (en majuscules) et s'incrémente."""
        t1 = self._new_ticket()
        t2 = self._new_ticket()
        self.assertEqual(t1.name, "CAR-001")
        self.assertEqual(t2.name, "CAR-002")

    def test_company_derived_from_location(self):
        """company_id remonte du site → alimente les record rules."""
        t = self._new_ticket()
        self.assertEqual(t.company_id, self.company)
        self.assertEqual(t.location_id, self.location)

    def test_priority_orders_queue(self):
        """Une priorité urgente passe devant un ticket arrivé plus tôt."""
        normal = self._new_ticket(priority='0')
        urgent = self._new_ticket(priority='2')
        self.assertEqual(self.service._get_next_waiting(), urgent)
        self.assertEqual(normal.position, 2)
        self.assertEqual(urgent.position, 1)

    def test_call_next_full_cycle(self):
        """Cycle complet via le guichet : appel → démarrage → fin."""
        ticket = self._new_ticket()
        self.counter.action_call_next()
        self.assertEqual(ticket.state, 'called')
        self.assertEqual(ticket.counter_id, self.counter)
        self.assertEqual(self.counter.current_ticket_id, ticket)
        ticket.action_start()
        self.assertEqual(ticket.state, 'serving')
        ticket.action_done()
        self.assertEqual(ticket.state, 'done')
        self.assertFalse(self.counter.current_ticket_id)

    def test_due_appointment_is_prioritized(self):
        """Un rendez-vous dont l'heure est passée remonte devant les normaux."""
        from datetime import datetime, timedelta
        self._new_ticket(priority='0')
        rdv = self._new_ticket(
            priority='0', channel='appointment',
            scheduled_time=datetime.now() - timedelta(minutes=5),
        )
        self.assertEqual(self.service._get_next_waiting(), rdv)

    def test_no_show(self):
        ticket = self._new_ticket()
        self.counter.action_call_next()
        ticket.action_no_show()
        self.assertEqual(ticket.state, 'no_show')
        self.assertFalse(self.counter.current_ticket_id)
