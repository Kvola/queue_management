# -*- coding: utf-8 -*-
"""Assistant « Nouvel établissement » — onboarding SaaS en un écran.

Créer un abonné à la main demande 5 étapes dans 4 menus (société, site,
files, guichet, utilisateur responsable). L'assistant fait tout d'un coup et
ouvre la fiche du site prête à l'emploi (QR d'entrée, borne, affichage).
"""
from odoo import _, api, fields, models


class QueueSetupWizard(models.TransientModel):
    _name = 'queue.setup.wizard'
    _description = "Assistant nouvel établissement"

    company_name = fields.Char("Nom de l'établissement", required=True)
    site_name = fields.Char(
        "Nom du site", help="Laissez vide pour reprendre le nom de "
                            "l'établissement (un site pourra être ajouté "
                            "ensuite pour chaque lieu physique).")
    street = fields.Char("Adresse")
    city = fields.Char("Ville")

    line_ids = fields.One2many(
        'queue.setup.wizard.line', 'wizard_id', string="Services",
        default=lambda self: [(0, 0, {'name': "Accueil", 'code': "A"})])

    manager_name = fields.Char("Nom du responsable")
    manager_email = fields.Char(
        "Email du responsable",
        help="Si renseigné, un utilisateur « Responsable file d'attente » "
             "est créé, limité à ce nouvel établissement. Vous définirez "
             "son mot de passe (ou lui enverrez une invitation) depuis sa "
             "fiche utilisateur.")

    def action_create(self):
        self.ensure_one()
        company = self.env['res.company'].create({'name': self.company_name})
        location = self.env['queue.location'].create({
            'name': self.site_name or self.company_name,
            'company_id': company.id,
            'street': self.street,
            'city': self.city,
        })
        services = self.env['queue.service'].create([{
            'name': line.name,
            'code': line.code,
            'location_id': location.id,
            'remote_enabled': line.remote_enabled,
            'appointment_enabled': line.appointment_enabled,
            'sequence': idx * 10,
        } for idx, line in enumerate(self.line_ids, start=1)])
        self.env['queue.counter'].create({
            'name': _("Guichet 1"),
            'location_id': location.id,
            'service_ids': [(6, 0, services.ids)],
        })
        if self.manager_email:
            # no_reset_password : pas d'email d'invitation automatique (le
            # SMTP peut ne pas être prêt) — l'admin gère depuis la fiche.
            self.env['res.users'].with_context(no_reset_password=True).create({
                'name': self.manager_name or self.manager_email,
                'login': self.manager_email,
                'email': self.manager_email,
                'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref('queue_management.group_queue_manager').id,
                ])],
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _("Site"),
            'res_model': 'queue.location',
            'res_id': location.id,
            'view_mode': 'form',
            'target': 'current',
        }


class QueueSetupWizardLine(models.TransientModel):
    _name = 'queue.setup.wizard.line'
    _description = "Assistant nouvel établissement — file"
    _order = 'id'

    wizard_id = fields.Many2one('queue.setup.wizard', required=True,
                                ondelete='cascade')
    name = fields.Char("Nom du service", required=True)
    code = fields.Char("Préfixe", required=True, size=4)
    remote_enabled = fields.Boolean("À distance")
    appointment_enabled = fields.Boolean("Rendez-vous")
