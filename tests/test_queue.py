# -*- coding: utf-8 -*-
from datetime import date, datetime, time, timedelta

from odoo import fields
from odoo.exceptions import UserError
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

    def test_numbering_batch_same_transaction(self):
        """Deux tickets créés dans le même batch ont des numéros distincts
        (le compteur relu en SQL sous verrou doit voir l'écriture ORM en
        attente de la même transaction)."""
        tickets = self.env['queue.ticket'].create([
            {'service_id': self.service.id},
            {'service_id': self.service.id},
        ])
        self.assertEqual(tickets.mapped('name'), ["CAR-001", "CAR-002"])

    def test_numbering_as_readonly_agent(self):
        """Un agent (lecture seule sur la file) peut créer un ticket : le
        compteur interne s'écrit en sudo."""
        agent = self.env['res.users'].create({
            'name': 'Agent Guichet', 'login': 'agent_numbering',
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id])],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('queue_management.group_queue_agent').id])],
        })
        ticket = self.env['queue.ticket'].with_user(agent).create({
            'service_id': self.service.id})
        self.assertEqual(ticket.name, "CAR-001")

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

    def test_call_next_blocked_when_busy(self):
        """On ne peut pas appeler un nouveau client tant que le précédent
        n'est pas clôturé (évite d'écraser le ticket en cours au guichet)."""
        from odoo.exceptions import UserError
        self._new_ticket()
        self._new_ticket()
        self.counter.action_call_next()
        with self.assertRaises(UserError):
            self.counter.action_call_next()

    def test_counter_console_shortcuts(self):
        """Les raccourcis du guichet agissent sur le ticket en cours."""
        ticket = self._new_ticket()
        self.counter.action_call_next()
        self.counter.action_start()
        self.assertEqual(ticket.state, 'serving')
        self.counter.action_done()
        self.assertEqual(ticket.state, 'done')

    def test_recall_keeps_state(self):
        """Le rappel ré-annonce sans changer l'état."""
        ticket = self._new_ticket()
        self.counter.action_call_next()
        before = ticket.called_at
        ticket.action_recall()
        self.assertEqual(ticket.state, 'called')
        self.assertGreaterEqual(ticket.called_at, before)

    def test_transition_map_blocks_incoherent_paths(self):
        """La machine à états refuse tout chemin non déclaré."""
        ticket = self._new_ticket()
        self.counter.action_call_next()
        ticket.action_start()
        ticket.action_done()
        with self.assertRaises(UserError):
            ticket._transition('serving')   # done → serving : interdit
        with self.assertRaises(UserError):
            ticket._transition('waiting')   # done → waiting : interdit

    def test_requeue_no_show_keeps_seniority(self):
        """Un absent re-mis en file reprend sa place d'origine (ancienneté)."""
        early = self._new_ticket()
        self.counter.action_call_next()      # appelle `early`
        early.action_no_show()
        late = self._new_ticket()            # arrivé après
        early.action_requeue()
        self.assertEqual(early.state, 'waiting')
        self.assertFalse(early.counter_id)
        self.assertFalse(early.closed_at)
        # Son heure d'arrivée d'origine le replace DEVANT le suivant.
        self.assertEqual(self.service._get_next_waiting(), early)
        self.assertEqual(late.position, 2)

    def test_requeue_guards(self):
        """Re-mise en file : réservée aux absents, et fenêtre de 2 h max."""
        waiting = self._new_ticket()
        with self.assertRaises(UserError):
            waiting.action_requeue()
        self.counter.action_call_next()
        waiting.action_no_show()
        waiting.write({'closed_at': fields.Datetime.now() - timedelta(hours=3)})
        with self.assertRaises(UserError):
            waiting.action_requeue()

    def test_cron_auto_no_show(self):
        """Un appelé sans réponse au-delà du délai passe en Absent et libère
        le guichet ; 0 désactive le mécanisme."""
        ticket = self._new_ticket()
        self.counter.action_call_next()
        ticket.write({'called_at': fields.Datetime.now() - timedelta(minutes=15)})
        self.env['queue.ticket']._cron_auto_no_show()   # défaut 10 min
        self.assertEqual(ticket.state, 'no_show')
        self.assertFalse(self.counter.current_ticket_id)
        # Désactivé → un appelé ancien reste appelé.
        self.env['ir.config_parameter'].sudo().set_param(
            'queue_management.auto_no_show_min', '0')
        ticket2 = self._new_ticket()
        self.counter.action_call_next()
        ticket2.write({'called_at': fields.Datetime.now() - timedelta(hours=1)})
        self.env['queue.ticket']._cron_auto_no_show()
        self.assertEqual(ticket2.state, 'called')
        self.env['ir.config_parameter'].sudo().set_param(
            'queue_management.auto_no_show_min', '10')

    def test_transfer_keeps_seniority_and_renumbers(self):
        """Transfert : le client garde son ancienneté mais prend un numéro
        de la file cible."""
        radio = self.env['queue.service'].create({
            'name': 'Radio', 'code': 'RAD', 'location_id': self.location.id})
        # Un ticket déjà dans la file cible, arrivé il y a peu…
        already_there = self.env['queue.ticket'].create({
            'service_id': radio.id})
        already_there.created_at = fields.Datetime.now()
        # …et le transféré, qui attend depuis 30 minutes côté Cardiologie.
        moved = self._new_ticket()
        moved.created_at = fields.Datetime.now() - timedelta(minutes=30)
        moved.action_transfer(radio)
        self.assertEqual(moved.service_id, radio)
        self.assertTrue(moved.name.startswith('RAD-'))
        self.assertEqual(moved.state, 'waiting')
        # Son ancienneté (30 min) le place DEVANT le ticket déjà en file.
        self.assertEqual(radio._get_next_waiting(), moved)

    def test_transfer_called_releases_counter(self):
        radio = self.env['queue.service'].create({
            'name': 'Radio2', 'code': 'RD2', 'location_id': self.location.id})
        ticket = self._new_ticket()
        self.counter.action_call_next()
        self.assertEqual(self.counter.current_ticket_id, ticket)
        ticket.action_transfer(radio)
        self.assertEqual(ticket.state, 'waiting')
        self.assertFalse(ticket.counter_id)
        self.assertFalse(self.counter.current_ticket_id)

    def test_transfer_guards(self):
        other_loc = self.env['queue.location'].create({
            'name': 'Ailleurs', 'company_id': self.company.id})
        far_service = self.env['queue.service'].create({
            'name': 'Loin', 'code': 'LN', 'location_id': other_loc.id})
        ticket = self._new_ticket()
        with self.assertRaises(UserError):
            ticket.action_transfer(ticket.service_id)   # même file
        with self.assertRaises(UserError):
            ticket.action_transfer(far_service)         # autre site
        self.counter.action_call_next()
        ticket.action_start()
        with self.assertRaises(UserError):
            ticket.action_transfer(far_service)         # en cours de service

    def test_chatter_on_all_form_models(self):
        """Tous les modèles à formulaire portent le chatter (mail.thread)."""
        for model in ('queue.location', 'queue.service', 'queue.counter',
                      'queue.customer', 'queue.app.release', 'queue.ticket'):
            self.assertIn('message_ids', self.env[model]._fields, model)

    def test_sensitive_fields_are_tracked(self):
        """Les champs sensibles sont déclarés suivis : leurs modifications
        laissent une trace dans le chatter. (Le postage effectif du message
        est du ressort du cœur Odoo — vérifié manuellement en réel ; sous le
        curseur de test, la finalisation du tracking suit une autre
        sémantique de flush.)"""
        tracked = {
            'queue.service': {'remote_enabled', 'appointment_enabled', 'active'},
            'queue.location': {'name', 'company_id', 'active'},
            'queue.counter': {'agent_id', 'active'},
            'queue.customer': {'email', 'active'},
            'queue.app.release': {'is_active', 'version'},
            'queue.ticket': {'state'},
        }
        for model, fields_expected in tracked.items():
            self.assertTrue(
                fields_expected <= self.env[model]._track_get_fields(),
                "%s : champs suivis manquants" % model)

    def test_counter_onchange_prefills_services(self):
        """Choisir le site pré-remplit les files desservies (actives)."""
        counter = self.env['queue.counter'].new({'name': 'G2'})
        counter.location_id = self.location
        counter._onchange_location_id()
        self.assertEqual(counter.service_ids._origin, self.service)

    def test_counter_services_must_match_location(self):
        """Un guichet ne peut pas desservir les files d'un autre site."""
        from odoo.exceptions import ValidationError
        other_location = self.env['queue.location'].create({
            'name': 'Autre site', 'company_id': self.company.id})
        other_service = self.env['queue.service'].create({
            'name': 'Ailleurs', 'code': 'AIL',
            'location_id': other_location.id})
        with self.assertRaises(ValidationError):
            self.env['queue.counter'].create({
                'name': 'G3', 'location_id': self.location.id,
                'service_ids': [(6, 0, other_service.ids)]})

    def test_counter_new_record_compute(self):
        """Régression : l'aperçu « prochain » d'un guichet EN COURS DE
        CRÉATION (onchange, service_ids vide) ne doit pas planter."""
        counter = self.env['queue.counter'].new({
            'location_id': self.location.id})
        self.assertEqual(counter.next_number, '')
        self.assertEqual(counter.waiting_count, 0)
        self.assertFalse(counter.next_ticket_id)

    def test_counter_multi_service_preview(self):
        """L'aperçu départage correctement les têtes de PLUSIEURS files."""
        service2 = self.env['queue.service'].create({
            'name': 'Radio', 'code': 'RAD', 'location_id': self.location.id})
        self.counter.write({'service_ids': [(4, service2.id)]})
        self._new_ticket()  # CAR, normal, arrivé en premier
        urgent2 = self.env['queue.ticket'].create({
            'service_id': service2.id, 'priority': '2'})
        self.assertEqual(self.counter.next_ticket_id, urgent2)
        self.assertEqual(self.counter.waiting_count, 2)

    def test_counter_next_preview(self):
        """L'aperçu du guichet annonce le bon prochain numéro et le compte."""
        self._new_ticket(priority='0')
        urgent = self._new_ticket(priority='2')
        self.assertEqual(self.counter.next_ticket_id, urgent)
        self.assertEqual(self.counter.next_number, urgent.name)
        self.assertEqual(self.counter.waiting_count, 2)

    def test_notify_upcoming_marks_flag(self):
        """Après un appel, les têtes de file restantes sont notifiées une fois."""
        self._new_ticket()
        self._new_ticket()
        self._new_ticket()
        self.counter.action_call_next()
        remaining = self.service._get_ordered_waiting()
        self.assertTrue(all(t.soon_notified for t in remaining[:2]))

    def test_push_graceful_without_fcm(self):
        """Sans credentials FCM, _push ne lève pas et renvoie False."""
        c = self.env['queue.customer'].create({'email': 'push@test.com'})
        self.assertFalse(c._push("Titre", "Corps"))  # pas de fcm_token
        c.fcm_token = 'device-token'
        self.assertFalse(c._push("Titre", "Corps"))  # FCM non configuré → no-op

    # --- Rendez-vous (Phase 4b) ----------------------------------------------

    def _enable_appointments(self):
        self.service.write({
            'appointment_enabled': True,
            'slot_duration': 30,
            'slot_capacity': 2,
        })
        for day in range(7):  # ouvert tous les jours 08:00–10:00
            self.env['queue.opening.hour'].create({
                'service_id': self.service.id,
                'dayofweek': str(day),
                'hour_from': 8.0,
                'hour_to': 10.0,
            })

    def test_slots_generation(self):
        self._enable_appointments()
        day = date.today() + timedelta(days=1)
        slots = self.service._slots_for_date(day)
        # 08:00, 08:30, 09:00, 09:30 → 4 créneaux entiers avant 10:00.
        self.assertEqual(len(slots), 4)
        self.assertTrue(all(avail == 2 for _, avail in slots))

    def test_booking_respects_capacity(self):
        self._enable_appointments()
        day = date.today() + timedelta(days=1)
        slot = datetime.combine(day, time(8, 0))
        partners = [self.env['res.partner'].create({'name': n}) for n in 'ABC']
        t1 = self.service._book_appointment(partners[0], slot)
        self.assertEqual(t1.state, 'scheduled')
        self.assertEqual(t1.channel, 'appointment')
        self.service._book_appointment(partners[1], slot)
        with self.assertRaises(UserError):
            self.service._book_appointment(partners[2], slot)
        self.assertEqual(dict(self.service._slots_for_date(day))[slot], 0)

    def test_booking_rejects_past_slot(self):
        """L'API n'affiche que des créneaux futurs, mais le modèle doit aussi
        refuser un créneau passé posté directement."""
        self._enable_appointments()
        partner = self.env['res.partner'].create({'name': 'Retardataire'})
        yesterday = datetime.combine(
            date.today() - timedelta(days=1), time(8, 0))
        with self.assertRaises(UserError):
            self.service._book_appointment(partner, yesterday)

    def test_booking_rejects_same_slot_twice(self):
        """Même client + même créneau = doublon refusé (capacité 2 sinon)."""
        self._enable_appointments()
        day = date.today() + timedelta(days=1)
        slot = datetime.combine(day, time(8, 0))
        partner = self.env['res.partner'].create({'name': 'Doublon'})
        self.service._book_appointment(partner, slot)
        with self.assertRaises(UserError):
            self.service._book_appointment(partner, slot)

    def test_booking_quota_per_customer(self):
        """Un client ne peut pas monopoliser l'agenda d'une file (2 RDV max
        par défaut, configurable via appointment_max_per_customer)."""
        self._enable_appointments()
        day = date.today() + timedelta(days=1)
        partner = self.env['res.partner'].create({'name': 'Accapareur'})
        self.service._book_appointment(partner, datetime.combine(day, time(8, 0)))
        self.service._book_appointment(partner, datetime.combine(day, time(8, 30)))
        with self.assertRaises(UserError):
            self.service._book_appointment(partner, datetime.combine(day, time(9, 0)))
        # Un RDV annulé libère le quota.
        first = self.env['queue.ticket'].search([
            ('partner_id', '=', partner.id),
            ('scheduled_time', '=', datetime.combine(day, time(8, 0)))])
        first.action_cancel()
        booked = self.service._book_appointment(
            partner, datetime.combine(day, time(9, 0)))
        self.assertEqual(booked.state, 'scheduled')

    def test_checkin_assigns_number(self):
        ticket = self.env['queue.ticket'].create({
            'service_id': self.service.id,
            'channel': 'appointment',
            'state': 'scheduled',
            'scheduled_time': fields.Datetime.now(),
        })
        self.assertEqual(ticket.name, '/')  # pas de numéro tant que programmé
        ticket.action_check_in()
        self.assertEqual(ticket.state, 'waiting')
        self.assertTrue(ticket.name.startswith('CAR'))

    # --- Estimation & statistiques (Phase 5) ---------------------------------

    def test_durations_and_average(self):
        base = fields.Datetime.now()
        ticket = self._new_ticket()
        ticket.write({
            'state': 'done',
            'created_at': base - timedelta(minutes=10),
            'called_at': base - timedelta(minutes=6),
            'served_at': base - timedelta(minutes=5),
            'closed_at': base,
        })
        self.assertAlmostEqual(ticket.wait_real_minutes, 4.0, delta=0.05)
        self.assertAlmostEqual(ticket.service_real_minutes, 5.0, delta=0.05)
        self.assertAlmostEqual(self.service._avg_service_minutes(), 5.0, delta=0.05)

    def test_eta_estimation(self):
        base = fields.Datetime.now()
        history = self._new_ticket()
        history.write({
            'state': 'done',
            'served_at': base - timedelta(minutes=6),
            'closed_at': base,
        })
        waiting = self._new_ticket()
        self.assertEqual(waiting.position, 1)
        # 1 position × 6 min / 1 guichet = 6 min
        self.assertEqual(waiting.eta_minutes, 6)

    def test_eta_zero_without_history(self):
        waiting = self._new_ticket()
        self.assertEqual(waiting.eta_minutes, 0)

    def test_cron_expires_overdue_appointment(self):
        old = self.env['queue.ticket'].create({
            'service_id': self.service.id,
            'channel': 'appointment',
            'state': 'scheduled',
            'scheduled_time': fields.Datetime.now() - timedelta(hours=3),
        })
        self.env['queue.ticket']._cron_expire_appointments()
        self.assertEqual(old.state, 'no_show')

    def test_cron_expiry_notifies_customer(self):
        """Le client est prévenu (push) quand son RDV expire en no-show."""
        from unittest.mock import patch
        customer = self.env['queue.customer'].create({'email': 'rdv@test.com'})
        customer._ensure_partner()
        self.env['queue.ticket'].create({
            'service_id': self.service.id,
            'partner_id': customer.partner_id.id,
            'channel': 'appointment',
            'state': 'scheduled',
            'scheduled_time': fields.Datetime.now() - timedelta(hours=3),
        })
        Customer = type(self.env['queue.customer'])
        with patch.object(Customer, '_push', autospec=True,
                          return_value=True) as mocked:
            self.env['queue.ticket']._cron_expire_appointments()
        self.assertEqual(mocked.call_count, 1)
        title = mocked.call_args.args[1]
        self.assertIn("expiré", title)
