from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
class QueueReportWizard(models.TransientModel):
    _name = 'queue.report.wizard'
    _description = 'Assistant Rapports Files d\'Attente'

    report_type = fields.Selection([
        ('daily', 'Rapport Quotidien'),
        ('weekly', 'Rapport Hebdomadaire'),
        ('monthly', 'Rapport Mensuel'),
        ('custom', 'Période Personnalisée')
    ], string='Type de Rapport', required=True, default='daily')
    
    date_from = fields.Date('Date de Début', required=True, default=fields.Date.today)
    date_to = fields.Date('Date de Fin', required=True, default=fields.Date.today)
    
    service_ids = fields.Many2many('queue.service', string='Services')
    include_charts = fields.Boolean('Inclure les Graphiques', default=True)
    format = fields.Selection([
        ('pdf', 'PDF'),
        ('xlsx', 'Excel')
    ], string='Format', default='pdf')

    @api.onchange('report_type')
    def _onchange_report_type(self):
        today = fields.Date.today()
        if self.report_type == 'daily':
            self.date_from = self.date_to = today
        elif self.report_type == 'weekly':
            self.date_from = today - timedelta(days=7)
            self.date_to = today
        elif self.report_type == 'monthly':
            self.date_from = today.replace(day=1)
            self.date_to = today

    def generate_report(self):
        """Générer le rapport"""
        data = {
            'date_from': self.date_from,
            'date_to': self.date_to,
            'service_ids': self.service_ids.ids,
            'include_charts': self.include_charts,
            'report_type': self.report_type
        }
        
        if self.format == 'pdf':
            return self.env.ref('queue_management.action_queue_custom_report').report_action(self, data=data)
        else:
            return self._generate_excel_report(data)

    def _generate_excel_report(self, data):
        """Générer rapport Excel"""
        # Implémentation de génération Excel avec xlsxwriter
        pass