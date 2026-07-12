# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSetupWizard(TransactionCase):
    """L'assistant « Nouvel établissement » crée tout, correctement câblé."""

    def test_full_onboarding(self):
        wizard = self.env['queue.setup.wizard'].create({
            'company_name': "Clinique des Palmiers",
            'city': "Abidjan",
            'manager_name': "Fatou Diabaté",
            'manager_email': "fatou@palmiers.test",
            'line_ids': [
                (0, 0, {'name': "Consultations", 'code': "C",
                        'remote_enabled': True}),
                (0, 0, {'name': "Pharmacie", 'code': "P",
                        'appointment_enabled': True}),
            ],
        })
        action = wizard.action_create()

        company = self.env['res.company'].search(
            [('name', '=', "Clinique des Palmiers")])
        self.assertEqual(len(company), 1)
        location = self.env['queue.location'].search(
            [('company_id', '=', company.id)])
        self.assertEqual(len(location), 1)
        self.assertEqual(location.name, "Clinique des Palmiers")  # défaut
        self.assertTrue(location.qr_token)
        self.assertEqual(action['res_id'], location.id)

        services = location.service_ids.sorted('sequence')
        self.assertEqual(services.mapped('code'), ['C', 'P'])
        self.assertTrue(services[0].remote_enabled)
        self.assertTrue(services[1].appointment_enabled)

        counter = location.counter_ids
        self.assertEqual(len(counter), 1)
        self.assertEqual(counter.service_ids, services)

        user = self.env['res.users'].search(
            [('login', '=', 'fatou@palmiers.test')])
        self.assertEqual(len(user), 1)
        self.assertEqual(user.company_ids, company)
        self.assertIn(self.env.ref('queue_management.group_queue_manager'),
                      user.group_ids)
        # Le nouveau responsable ne voit QUE son établissement.
        visible = self.env['queue.location'].with_user(user).search([])
        self.assertEqual(visible, location)

    def test_onboarding_without_manager(self):
        wizard = self.env['queue.setup.wizard'].create({
            'company_name': "Cabinet Solo",
            'site_name': "Cabinet Solo — Centre",
        })
        wizard.action_create()
        location = self.env['queue.location'].search(
            [('name', '=', "Cabinet Solo — Centre")])
        self.assertEqual(len(location), 1)
        # La ligne de file par défaut (« Accueil ») a bien été créée.
        self.assertEqual(location.service_ids.mapped('code'), ['A'])
