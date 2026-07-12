# -*- coding: utf-8 -*-

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCustomerTokenAcl(TransactionCase):
    """Les secrets du client (token, token_expiry, fcm_token) ne sont lisibles
    que par l'administrateur système, et les agents n'ont AUCUN accès au
    fichier des clients mobiles (ils n'en ont pas besoin : les tickets
    référencent ``res.partner``).
    """

    SECRET_FIELDS = ['token', 'token_expiry', 'fcm_token']

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['queue.customer'].create({
            'name': 'Client Test', 'email': 'client.token@test.com',
        })
        cls.customer.sudo().write({'token': 'sess_secret', 'fcm_token': 'fcm_secret'})
        agent_group = cls.env.ref('queue_management.group_queue_agent')
        base_user = cls.env.ref('base.group_user')
        cls.agent = cls.env['res.users'].create({
            'name': 'Agent Test', 'login': 'queue_agent_test',
            'email': 'agent.token@test.com',
            'group_ids': [(6, 0, [base_user.id, agent_group.id])],
        })

    def test_fields_are_group_restricted(self):
        for fname in self.SECRET_FIELDS:
            self.assertEqual(
                self.env['queue.customer']._fields[fname].groups,
                'base.group_system',
            )

    def test_agent_has_no_access_at_all(self):
        """Depuis l'audit 2026-07-12 : plus d'ACL agent sur queue.customer."""
        cust = self.customer.with_user(self.agent)
        with self.assertRaises(AccessError):
            cust.read(['email'])
        with self.assertRaises(AccessError):
            cust.env['queue.customer'].search([])

    def test_agent_cannot_read_token(self):
        cust = self.customer.with_user(self.agent)
        with self.assertRaises(AccessError):
            cust.read(['token'])

    def test_agent_cannot_read_fcm_token(self):
        cust = self.customer.with_user(self.agent)
        with self.assertRaises(AccessError):
            cust.read(['fcm_token'])

    def test_system_admin_can_read_token(self):
        self.assertEqual(self.customer.token, 'sess_secret')


@tagged('post_install', '-at_install')
class TestCustomerTenantIsolation(TransactionCase):
    """Un responsable ne voit que les clients ayant un ticket dans SES sociétés
    (le client mobile est global : pas de company_id, la visibilité passe par
    ses tickets — cf. rule_queue_customer_manager).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company_a = env['res.company'].create({'name': 'Hôpital A'})
        cls.company_b = env['res.company'].create({'name': 'Mairie B'})
        loc_a = env['queue.location'].create({
            'name': 'Site A', 'company_id': cls.company_a.id})
        loc_b = env['queue.location'].create({
            'name': 'Site B', 'company_id': cls.company_b.id})
        cls.service_a = env['queue.service'].create({
            'name': 'File A', 'code': 'A', 'location_id': loc_a.id})
        cls.service_b = env['queue.service'].create({
            'name': 'File B', 'code': 'B', 'location_id': loc_b.id})

        cls.customer_a = env['queue.customer'].create({'email': 'a@tenant.test'})
        cls.customer_b = env['queue.customer'].create({'email': 'b@tenant.test'})
        cls.customer_none = env['queue.customer'].create({'email': 'zero@tenant.test'})
        (cls.customer_a + cls.customer_b)._ensure_partner()
        env['queue.ticket'].create({
            'service_id': cls.service_a.id,
            'partner_id': cls.customer_a.partner_id.id})
        env['queue.ticket'].create({
            'service_id': cls.service_b.id,
            'partner_id': cls.customer_b.partner_id.id})

        manager_group = env.ref('queue_management.group_queue_manager')
        base_user = env.ref('base.group_user')
        cls.manager_a = env['res.users'].create({
            'name': 'Manager A', 'login': 'queue_manager_a',
            'email': 'manager.a@tenant.test',
            'company_id': cls.company_a.id,
            'company_ids': [(6, 0, [cls.company_a.id])],
            'group_ids': [(6, 0, [base_user.id, manager_group.id])],
        })

    def test_manager_sees_only_his_tenant_customers(self):
        visible = self.env['queue.customer'].with_user(self.manager_a).search([])
        self.assertIn(self.customer_a, visible)
        self.assertNotIn(self.customer_b, visible)
        # Un client sans aucun ticket n'est visible d'aucun établissement.
        self.assertNotIn(self.customer_none, visible)

    def test_manager_cannot_read_foreign_customer(self):
        with self.assertRaises(AccessError):
            self.customer_b.with_user(self.manager_a).read(['email'])

    def test_manager_cannot_write_foreign_customer(self):
        with self.assertRaises(AccessError):
            self.customer_b.with_user(self.manager_a).write({'name': 'Piraté'})

    def test_manager_cannot_create_or_unlink(self):
        """Les clients s'auto-inscrivent : pas de création/suppression manuelle."""
        Customer = self.env['queue.customer'].with_user(self.manager_a)
        with self.assertRaises(AccessError):
            Customer.create({'email': 'nouveau@tenant.test'})
        with self.assertRaises(AccessError):
            self.customer_a.with_user(self.manager_a).unlink()
