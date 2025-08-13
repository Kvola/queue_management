# models/queue_report_preview.py
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class QueueReportPreview(models.TransientModel):
    _name = 'queue.report.preview'
    _description = 'Aperçu du Rapport File d\'Attente'

    # Champs de données
    preview_data = fields.Text(string="Données d'Aperçu", readonly=True)
    summary_stats = fields.Text(string="Statistiques Résumées", readonly=True)
    wizard_id = fields.Many2one('queue.report.wizard', string="Assistant de Rapport")
    
    # Champs calculés
    period_summary = fields.Char(string="Période", compute='_compute_period_summary')
    services_summary = fields.Char(string="Services", compute='_compute_services_summary')
    elements_included = fields.Text(string="Éléments Inclus", compute='_compute_elements_included')

    @api.depends('wizard_id')
    def _compute_period_summary(self):
        for preview in self:
            if preview.wizard_id:
                preview.period_summary = f"{preview.wizard_id.date_from} - {preview.wizard_id.date_to} ({preview.wizard_id.days_count} jours)"
            else:
                preview.period_summary = "Non spécifié"

    @api.depends('wizard_id')
    def _compute_services_summary(self):
        for preview in self:
            if preview.wizard_id:
                services = preview.wizard_id.service_ids
                if not services:
                    preview.services_summary = "Tous les services"
                elif len(services) == 1:
                    preview.services_summary = services[0].name
                else:
                    preview.services_summary = f"{len(services)} services sélectionnés"
            else:
                preview.services_summary = "Non spécifié"

    @api.depends('wizard_id')
    def _compute_elements_included(self):
        for preview in self:
            if preview.wizard_id:
                elements = []
                if preview.wizard_id.include_statistics:
                    elements.append("Statistiques avancées")
                if preview.wizard_id.include_charts:
                    elements.append("Graphiques")
                if preview.wizard_id.include_satisfaction:
                    elements.append("Analyse de satisfaction")
                if preview.wizard_id.include_details:
                    elements.append(f"Détails des tickets (max {preview.wizard_id.max_detail_tickets})")
                
                preview.elements_included = "\n".join(elements) if elements else "Aucun élément spécifique"
            else:
                preview.elements_included = "Non spécifié"

    def generate_full_report(self):
        """Action pour générer le rapport complet à partir de l'aperçu"""
        self.ensure_one()
        if not self.wizard_id:
            raise UserError(_("Aucun assistant de rapport associé à cet aperçu"))
        
        return self.wizard_id.generate_report()