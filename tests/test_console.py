# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestConsole(TransactionCase):
    """Console agent : présence (rejoindre/quitter) et données."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company = env['res.company'].create({'name': 'Console Hôpital'})
        cls.location = env['queue.location'].create({
            'name': 'Console Site', 'company_id': cls.company.id})
        cls.service = env['queue.service'].create({
            'name': 'Console Svc', 'code': 'CS', 'location_id': cls.location.id})
        cls.counter_a = env['queue.counter'].create({
            'name': 'Guichet A', 'location_id': cls.location.id,
            'service_ids': [(6, 0, cls.service.ids)]})
        cls.counter_b = env['queue.counter'].create({
            'name': 'Guichet B', 'location_id': cls.location.id,
            'service_ids': [(6, 0, cls.service.ids)]})
        cls.agent = env['res.users'].create({
            'name': 'Agent Console', 'login': 'console_agent',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
            'group_ids': [(6, 0, [
                env.ref('base.group_user').id,
                env.ref('queue_management.group_queue_agent').id])],
        })

    def test_join_is_exclusive_and_leave_works(self):
        """Rejoindre un guichet quitte l'autre ; deux agents peuvent
        partager un même guichet."""
        Counter = self.env['queue.counter'].with_user(self.agent)
        Counter.browse(self.counter_a.id).action_join()
        self.assertIn(self.agent, self.counter_a.agent_ids)
        # Rejoindre B → quitte A automatiquement.
        Counter.browse(self.counter_b.id).action_join()
        self.assertNotIn(self.agent, self.counter_a.agent_ids)
        self.assertIn(self.agent, self.counter_b.agent_ids)
        # Un 2e agent partage le guichet B.
        agent2 = self.env['res.users'].create({
            'name': 'Agent 2', 'login': 'console_agent2',
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id])],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('queue_management.group_queue_agent').id])],
        })
        self.counter_b.with_user(agent2).action_join()
        self.assertEqual(len(self.counter_b.agent_ids), 2)
        # Quitter.
        Counter.browse(self.counter_b.id).action_leave()
        self.assertNotIn(self.agent, self.counter_b.agent_ids)
        self.assertIn(agent2, self.counter_b.agent_ids)

    def test_console_data_full_cycle(self):
        """Les données de console suivent le cycle appel → service → fin."""
        Counter = self.env['queue.counter'].with_user(self.agent)
        Counter.browse(self.counter_a.id).action_join()
        ticket = self.env['queue.ticket'].create(
            {'service_id': self.service.id})
        data = Counter.get_console_data(self.counter_a.id)
        self.assertTrue(data['joined'])
        self.assertFalse(data['busy'])
        self.assertEqual(data['waiting'], 1)
        self.assertEqual(data['next_number'], ticket.name)
        Counter.browse(self.counter_a.id).action_call_next()
        data = Counter.get_console_data(self.counter_a.id)
        self.assertTrue(data['busy'])
        self.assertEqual(data['ticket'], ticket.name)
        self.assertEqual(data['ticket_state'], 'called')

    def test_console_respects_tenant_isolation(self):
        """Un agent ne voit que les guichets de SES établissements."""
        other_company = self.env['res.company'].create({'name': 'Autre Cie'})
        other_loc = self.env['queue.location'].create({
            'name': 'Autre Site', 'company_id': other_company.id})
        other_counter = self.env['queue.counter'].create({
            'name': 'Guichet X', 'location_id': other_loc.id})
        data = self.env['queue.counter'].with_user(
            self.agent).get_console_data()
        ids = [c['id'] for c in data['counters']]
        self.assertIn(self.counter_a.id, ids)
        self.assertNotIn(other_counter.id, ids)
