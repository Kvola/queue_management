# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class QueueServiceFromTemplateWizard(models.TransientModel):
    """Ajoute des services à un site existant depuis les modèles d'un secteur."""

    _name = 'queue.service.from.template.wizard'
    _description = "Ajouter des services depuis un modèle"

    location_id = fields.Many2one(
        'queue.location', string="Site", required=True,
        default=lambda self: self.env.context.get('active_id'))
    sector_id = fields.Many2one('queue.sector', string="Secteur", required=True)
    template_ids = fields.Many2many(
        'queue.service.template', string="Services à ajouter",
        domain="[('sector_id', '=', sector_id)]")

    @api.onchange('sector_id')
    def _onchange_sector_id(self):
        self.template_ids = self.sector_id.template_ids

    def action_add(self):
        self.ensure_one()
        existing = set(self.location_id.service_ids.mapped('code'))
        seq = max(self.location_id.service_ids.mapped('sequence') or [0])
        created = self.env['queue.service']
        for tmpl in self.template_ids.sorted('sequence'):
            # Le préfixe est unique par site : on saute un modèle déjà présent.
            if tmpl.code in existing:
                continue
            seq += 10
            created |= self.env['queue.service'].create(
                tmpl._to_service_vals(self.location_id, sequence=seq))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Services"),
            'res_model': 'queue.service',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
        }
