# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDashboard(TransactionCase):
    """Données du tableau de bord : exactitude des KPIs + isolation tenant."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company_a = env['res.company'].create({'name': 'Hôpital Dash A'})
        cls.company_b = env['res.company'].create({'name': 'Mairie Dash B'})
        cls.loc_a = env['queue.location'].create({
            'name': 'Site Dash A', 'company_id': cls.company_a.id})
        cls.loc_b = env['queue.location'].create({
            'name': 'Site Dash B', 'company_id': cls.company_b.id})
        cls.service_a = env['queue.service'].create({
            'name': 'File Dash', 'code': 'DSH', 'location_id': cls.loc_a.id})
        cls.counter_a = env['queue.counter'].create({
            'name': 'Guichet Dash', 'location_id': cls.loc_a.id,
            'service_ids': [(6, 0, cls.service_a.ids)]})
        manager_group = env.ref('queue_management.group_queue_manager')
        base_user = env.ref('base.group_user')
        cls.manager_a = env['res.users'].create({
            'name': 'Manager Dash A', 'login': 'queue_dash_manager_a',
            'company_id': cls.company_a.id,
            'company_ids': [(6, 0, [cls.company_a.id])],
            'group_ids': [(6, 0, [base_user.id, manager_group.id])],
        })

    def _ticket(self):
        return self.env['queue.ticket'].create({'service_id': self.service_a.id})

    def test_kpis_and_live_state(self):
        # 3 tickets : 1 servi, 1 absent, 1 encore en attente.
        served = self._ticket()
        absent = self._ticket()
        waiting = self._ticket()
        self.counter_a.action_call_next()   # appelle `served`
        served.action_start()
        served.action_done()
        self.counter_a.action_call_next()   # appelle `absent`
        absent.action_no_show()
        self.counter_a.action_call_next()   # appelle `waiting`
        data = self.env['queue.location'].get_dashboard_data(self.loc_a.id)
        kpis = data['kpis']
        self.assertEqual(kpis['done_today'], 1)
        self.assertEqual(kpis['no_show_rate'], 50.0)  # 1 absent / (1 servi + 1)
        # `waiting` a été appelé par le 3e action_call_next → plus personne
        # en file, le guichet est occupé avec lui.
        self.assertEqual(kpis['waiting'], 0)
        counter = data['counters'][0]
        self.assertTrue(counter['busy'])
        self.assertEqual(counter['ticket'], waiting.name)
        self.assertEqual(counter['ticket_state'], 'called')
        svc = data['services'][0]
        self.assertEqual(svc['code'], 'DSH')
        self.assertEqual(svc['next_number'], '')

    def test_next_in_queue_shown(self):
        first = self._ticket()
        self._ticket()
        data = self.env['queue.location'].get_dashboard_data(self.loc_a.id)
        svc = data['services'][0]
        self.assertEqual(svc['waiting'], 2)
        self.assertEqual(svc['next_number'], first.name)

    def test_agent_can_work_from_dashboard(self):
        """Un agent (lecture seule sur la config) peut consulter le dashboard
        ET actionner son guichet (appeler/servir) — c'est son poste de
        travail depuis la Phase H."""
        agent = self.env['res.users'].create({
            'name': 'Agent Dash', 'login': 'queue_dash_agent',
            'company_id': self.company_a.id,
            'company_ids': [(6, 0, [self.company_a.id])],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('queue_management.group_queue_agent').id])],
        })
        ticket = self._ticket()
        data = self.env['queue.location'].with_user(agent).get_dashboard_data(
            self.loc_a.id)
        self.assertEqual(data['location_id'], self.loc_a.id)
        self.assertEqual(data['counters'][0]['waiting'], 1)
        # Action depuis la carte guichet, en tant qu'agent.
        self.counter_a.with_user(agent).action_call_next()
        self.assertEqual(ticket.state, 'called')
        self.counter_a.with_user(agent).action_start()
        self.counter_a.with_user(agent).action_done()
        self.assertEqual(ticket.state, 'done')

    def test_manager_only_sees_his_locations(self):
        Location = self.env['queue.location'].with_user(self.manager_a)
        data = Location.get_dashboard_data()
        ids = [l['id'] for l in data['locations']]
        self.assertIn(self.loc_a.id, ids)
        self.assertNotIn(self.loc_b.id, ids)
        # Demander explicitement le site d'un autre tenant ne le révèle pas :
        # les record rules filtrent, on retombe sur son propre site.
        data_b = Location.get_dashboard_data(self.loc_b.id)
        self.assertNotEqual(data_b['location_id'], self.loc_b.id)