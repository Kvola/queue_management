/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

class QueueDashboardReports extends Component {
    static template = "queue_management.QueueDashboardReports";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        
        this.state = useState({
            reportData: null,
            isLoading: true,
            selectedTab: 'overview',
            chartData: null
        });

        onWillStart(async () => {
            await this.loadReportData();
        });
    }

    async loadReportData() {
        try {
            // Récupérer les données du contexte ou du serveur
            const context = this.props.action?.context || {};
            
            if (context.default_report_data) {
                this.state.reportData = context.default_report_data;
            } else {
                // Charger depuis le serveur si pas de données en contexte
                this.state.reportData = await this.orm.call(
                    "queue.service", 
                    "get_dashboard_report_data", 
                    []
                );
            }
            
            this.prepareChartData();
        } catch (error) {
            console.error("Error loading report data:", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    prepareChartData() {
        if (!this.state.reportData) return;

        const data = this.state.reportData;
        
        this.state.chartData = {
            serviceEfficiency: {
                labels: data.services.map(s => s.name),
                datasets: [{
                    label: 'Efficacité (%)',
                    data: data.services.map(s => this.calculateServiceEfficiency(s)),
                    backgroundColor: 'rgba(54, 162, 235, 0.8)'
                }]
            },
            waitingTrends: {
                labels: data.historical_data.slice(-10).map(d => 
                    new Date(d.time).toLocaleDateString()
                ),
                datasets: [{
                    label: 'Temps d\'attente moyen (min)',
                    data: data.historical_data.slice(-10).map(d => d.avg_wait_time),
                    borderColor: 'rgba(255, 99, 132, 1)',
                    fill: false
                }]
            },
            ticketDistribution: {
                labels: ['Terminés', 'En Attente', 'En Service', 'Annulés'],
                datasets: [{
                    data: [
                        data.summary.completed_tickets,
                        data.summary.waiting_tickets,
                        data.summary.serving_tickets,
                        data.summary.cancelled_tickets + data.summary.no_show_tickets
                    ],
                    backgroundColor: [
                        'rgba(40, 167, 69, 0.8)',
                        'rgba(255, 193, 7, 0.8)',
                        'rgba(0, 123, 255, 0.8)',
                        'rgba(108, 117, 125, 0.8)'
                    ]
                }]
            }
        };
    }

    calculateServiceEfficiency(service) {
        const total = service.waiting_count + service.serving_count + service.served_count;
        return total > 0 ? Math.round((service.served_count / total) * 100) : 0;
    }

    // Gestionnaires d'événements
    onTabChange(ev) {
        this.state.selectedTab = ev.currentTarget.dataset.tab;
    }

    async onExportReport(ev) {
        const format = ev.currentTarget.dataset.format;
        const includeCharts = document.getElementById('includeCharts')?.checked || false;
        
        try {
            const exportData = this.prepareExportData();
            const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-');
            const filename = `dashboard_report_${timestamp}.${format}`;

            switch (format) {
                case 'csv':
                    this.exportToCSV(exportData, filename);
                    break;
                case 'excel':
                    await this.exportToExcel(exportData, filename);
                    break;
                case 'json':
                    this.exportToJSON(exportData, filename);
                    break;
                case 'pdf':
                    if (includeCharts && this.areChartsAvailableForExport()) {
                        await this.exportToPDF(exportData, filename);
                    } else {
                        await this.exportToPDFWithoutCharts(exportData, filename);
                    }
                    break;
                default:
                    throw new Error('Format d\'export non supporté');
            }

            this.notification.add(`Export ${format.toUpperCase()} généré avec succès`, {
                type: "success"
            });
        } catch (error) {
            console.error("Export error:", error);
            this.notification.add(`Erreur lors de l'export: ${this.getErrorMessage(error)}`, {
                type: "danger"
            });
        }
    }

    onClose() {
        this.action.doAction({ type: 'ir.actions.act_window_close' });
    }

    // Getters pour le template
    get reportData() {
        return this.state.reportData;
    }

    get isOverviewTab() {
        return this.state.selectedTab === 'overview';
    }

    get isEfficiencyTab() {
        return this.state.selectedTab === 'efficiency';
    }

    get isTrendsTab() {
        return this.state.selectedTab === 'trends';
    }

    get isRecommendationsTab() {
        return this.state.selectedTab === 'recommendations';
    }

    // Méthodes de formatage
    formatPercentage(value) {
        return `${Math.round(value * 100) / 100}%`;
    }

    formatDuration(minutes) {
        if (minutes < 60) {
            return `${Math.round(minutes)} min`;
        }
        const hours = Math.floor(minutes / 60);
        const mins = Math.round(minutes % 60);
        return `${hours}h ${mins}min`;
    }

    getRecommendationIcon(type) {
        const icons = {
            'capacity': 'fa-expand',
            'efficiency': 'fa-clock-o',
            'retention': 'fa-users'
        };
        return icons[type] || 'fa-info-circle';
    }

    getRecommendationColor(priority) {
        const colors = {
            'high': 'text-danger',
            'medium': 'text-warning',
            'low': 'text-info'
        };
        return colors[priority] || 'text-secondary';
    }
}

// Template pour les rapports
const reportsTemplate = `
<div class="queue-reports-container h-100 d-flex flex-column">
    <!-- Header -->
    <div class="reports-header bg-primary text-white p-3 d-flex justify-content-between align-items-center">
        <h3 class="mb-0">
            <i class="fa fa-chart-line"/> Rapports Queue Management
        </h3>
        <div>
            <div class="btn-group me-2">
                <button class="btn btn-outline-light btn-sm dropdown-toggle" data-bs-toggle="dropdown">
                    <i class="fa fa-download"/> Exporter
                </button>
                <ul class="dropdown-menu">
                    <li><a class="dropdown-item" href="#" t-on-click="onExportReport" data-format="pdf">
                        <i class="fa fa-file-pdf-o"/> PDF
                    </a></li>
                    <li><a class="dropdown-item" href="#" t-on-click="onExportReport" data-format="excel">
                        <i class="fa fa-file-excel-o"/> Excel
                    </a></li>
                </ul>
            </div>
            <button class="btn btn-outline-light btn-sm" t-on-click="onClose">
                <i class="fa fa-times"/> Fermer
            </button>
        </div>
    </div>

    <!-- Loading -->
    <div class="text-center py-5" t-if="state.isLoading">
        <div class="spinner-border text-primary" role="status"></div>
        <p class="mt-3">Génération du rapport...</p>
    </div>

    <!-- Content -->
    <div class="flex-grow-1 d-flex flex-column" t-if="!state.isLoading and reportData">
        <!-- Navigation Tabs -->
        <div class="reports-nav bg-light border-bottom">
            <ul class="nav nav-tabs border-bottom-0">
                <li class="nav-item">
                    <button class="nav-link" 
                            t-att-class="isOverviewTab ? 'active' : ''"
                            t-on-click="onTabChange"
                            data-tab="overview">
                        <i class="fa fa-tachometer"/> Vue d'ensemble
                    </button>
                </li>
                <li class="nav-item">
                    <button class="nav-link"
                            t-att-class="isEfficiencyTab ? 'active' : ''"
                            t-on-click="onTabChange"
                            data-tab="efficiency">
                        <i class="fa fa-bar-chart"/> Efficacité
                    </button>
                </li>
                <li class="nav-item">
                    <button class="nav-link"
                            t-att-class="isTrendsTab ? 'active' : ''"
                            t-on-click="onTabChange"
                            data-tab="trends">
                        <i class="fa fa-line-chart"/> Tendances
                    </button>
                </li>
                <li class="nav-item">
                    <button class="nav-link"
                            t-att-class="isRecommendationsTab ? 'active' : ''"
                            t-on-click="onTabChange"
                            data-tab="recommendations">
                        <i class="fa fa-lightbulb-o"/> Recommandations
                    </button>
                </li>
            </ul>
        </div>

        <!-- Tab Content -->
        <div class="reports-content flex-grow-1 p-4 overflow-auto">
            
            <!-- Overview Tab -->
            <div t-if="isOverviewTab">
                <div class="row mb-4">
                    <div class="col-12">
                        <h4>Résumé Exécutif</h4>
                        <p class="text-muted">
                            Rapport généré le <t t-esc="new Date(reportData.report_generated_at).toLocaleString()"/>
                        </p>
                    </div>
                </div>

                <!-- KPIs -->
                <div class="row mb-4">
                    <div class="col-md-3 mb-3">
                        <div class="card bg-primary text-white h-100">
                            <div class="card-body text-center">
                                <h2 class="card-title" t-esc="reportData.summary.total_tickets"/>
                                <p class="card-text">Total Tickets</p>
                                <small>Aujourd'hui</small>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3 mb-3">
                        <div class="card bg-success text-white h-100">
                            <div class="card-body text-center">
                                <h2 class="card-title" t-esc="formatPercentage(reportData.summary.completion_rate)"/>
                                <p class="card-text">Taux de Completion</p>
                                <small>Performance globale</small>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3 mb-3">
                        <div class="card bg-warning text-white h-100">
                            <div class="card-body text-center">
                                <h2 class="card-title" t-esc="formatDuration(reportData.summary.average_wait_time)"/>
                                <p class="card-text">Temps d'Attente Moyen</p>
                                <small>Tous services confondus</small>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3 mb-3">
                        <div class="card bg-info text-white h-100">
                            <div class="card-body text-center">
                                <h2 class="card-title" t-esc="Math.round(reportData.efficiency_metrics.customer_satisfaction_score)"/>
                                <p class="card-text">Score Satisfaction</p>
                                <small>Sur 100</small>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Services Overview -->
                <div class="row mb-4">
                    <div class="col-12">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="card-title mb-0">Performance des Services</h5>
                            </div>
                            <div class="card-body">
                                <div class="table-responsive">
                                    <table class="table table-striped">
                                        <thead>
                                            <tr>
                                                <th>Service</th>
                                                <th>Tickets Traités</th>
                                                <th>Temps Moyen</th>
                                                <th>Efficacité</th>
                                                <th>Statut</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            <tr t-foreach="reportData.services" t-as="service" t-key="service.id">
                                                <td><strong t-esc="service.name"/></td>
                                                <td t-esc="service.total_tickets_today"/>
                                                <td t-esc="formatDuration(service.avg_waiting_time)"/>
                                                <td>
                                                    <span class="badge"
                                                          t-att-class="calculateServiceEfficiency(service) > 80 ? 'badge-success' : calculateServiceEfficiency(service) > 60 ? 'badge-warning' : 'badge-danger'">
                                                        <t t-esc="calculateServiceEfficiency(service)"/>%
                                                    </span>
                                                </td>
                                                <td>
                                                    <span class="badge"
                                                          t-att-class="service.is_open ? 'badge-success' : 'badge-danger'">
                                                        <t t-if="service.is_open">Actif</t>
                                                        <t t-else="">Fermé</t>
                                                    </span>
                                                </td>
                                            </tr>
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Quick Stats -->
                <div class="row">
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="card-title mb-0">Répartition des Tickets</h5>
                            </div>
                            <div class="card-body">
                                <canvas id="ticketDistributionChart" style="height: 200px;"></canvas>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="card-title mb-0">Métriques Clés</h5>
                            </div>
                            <div class="card-body">
                                <div class="row">
                                    <div class="col-6 text-center mb-3">
                                        <h4 class="text-primary" t-esc="reportData.summary.active_services"/>
                                        <small class="text-muted">Services Actifs</small>
                                    </div>
                                    <div class="col-6 text-center mb-3">
                                        <h4 class="text-success" t-esc="reportData.efficiency_metrics.peak_hours.highest_load_hour"/>
                                        <small class="text-muted">Heure de Pointe</small>
                                    </div>
                                    <div class="col-6 text-center">
                                        <h4 class="text-warning" t-esc="reportData.efficiency_metrics.bottleneck_services.length"/>
                                        <small class="text-muted">Services Surchargés</small>
                                    </div>
                                    <div class="col-6 text-center">
                                        <h4 class="text-info" t-esc="formatDuration(reportData.efficiency_metrics.avg_service_time)"/>
                                        <small class="text-muted">Durée Moy. Service</small>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Efficiency Tab -->
            <div t-if="isEfficiencyTab">
                <div class="row mb-4">
                    <div class="col-12">
                        <h4>Analyse d'Efficacité</h4>
                        <p class="text-muted">Analyse détaillée des performances de chaque service</p>
                    </div>
                </div>

                <!-- Service Efficiency Chart -->
                <div class="row mb-4">
                    <div class="col-12">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="card-title mb-0">Efficacité par Service</h5>
                            </div>
                            <div class="card-body">
                                <canvas id="serviceEfficiencyChart" style="height: 300px;"></canvas>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Bottlenecks Analysis -->
                <div class="row mb-4">
                    <div class="col-md-8">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="card-title mb-0">Services en Goulot d'Étranglement</h5>
                            </div>
                            <div class="card-body">
                                <div t-if="!reportData.efficiency_metrics.bottleneck_services.length" 
                                     class="text-center text-muted py-3">
                                    <i class="fa fa-check-circle fa-2x text-success mb-2"/>
                                    <p>Aucun goulot d'étranglement détecté</p>
                                </div>
                                <div t-else="">
                                    <div t-foreach="reportData.efficiency_metrics.bottleneck_services" 
                                         t-as="bottleneck" 
                                         t-key="bottleneck.name"
                                         class="alert mb-2"
                                         t-att-class="bottleneck.severity === 'critical' ? 'alert-danger' : 'alert-warning'">
                                        <h6 class="alert-heading mb-1">
                                            <i class="fa fa-exclamation-triangle"/> <t t-esc="bottleneck.name"/>
                                        </h6>
                                        <p class="mb-1">
                                            Capacité: <strong t-esc="bottleneck.capacity_percentage"/>%</strong> |
                                            En attente: <strong t-esc="bottleneck.waiting_count"/> tickets</strong>
                                        </p>
                                        <small>
                                            Criticité: 
                                            <span class="badge"
                                                  t-att-class="bottleneck.severity === 'critical' ? 'badge-danger' : 'badge-warning'">
                                                <t t-esc="bottleneck.severity"/>
                                            </span>
                                        </small>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="card-title mb-0">Heures de Pointe</h5>
                            </div>
                            <div class="card-body">
                                <div class="mb-3">
                                    <small class="text-muted">Pic Matinal</small>
                                    <div class="fw-bold" t-esc="reportData.efficiency_metrics.peak_hours.morning_peak"/>
                                </div>
                                <div class="mb-3">
                                    <small class="text-muted">Pic Après-midi</small>
                                    <div class="fw-bold" t-esc="reportData.efficiency_metrics.peak_hours.afternoon_peak"/>
                                </div>
                                <div>
                                    <small class="text-muted">Charge Maximale</small>
                                    <div class="fw-bold text-warning" t-esc="reportData.efficiency_metrics.peak_hours.highest_load_hour"/>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Service Usage Patterns -->
                <div class="row">
                    <div class="col-12">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="card-title mb-0">Patterns d'Utilisation</h5>
                            </div>
                            <div class="card-body">
                                <div class="table-responsive">
                                    <table class="table table-striped">
                                        <thead>
                                            <tr>
                                                <th>Service</th>
                                                <th>Niveau d'Usage</th>
                                                <th>Efficacité</th>
                                                <th>Recommandation</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            <tr t-foreach="reportData.trend_analysis.service_usage_patterns" 
                                                t-as="pattern" 
                                                t-key="pattern.name">
                                                <td t-esc="pattern.name"/>
                                                <td>
                                                    <span class="badge"
                                                          t-att-class="pattern.usage_level === 'high' ? 'badge-success' : pattern.usage_level === 'medium' ? 'badge-warning' : 'badge-secondary'">
                                                        <t t-esc="pattern.usage_level"/>
                                                    </span>
                                                </td>
                                                <td>
                                                    <div class="progress" style="height: 20px;">
                                                        <div class="progress-bar"
                                                             t-att-class="pattern.efficiency > 80 ? 'bg-success' : pattern.efficiency > 60 ? 'bg-warning' : 'bg-danger'"
                                                             t-att-style="'width: ' + pattern.efficiency + '%'"
                                                             t-esc="pattern.efficiency + '%'">
                                                        </div>
                                                    </div>
                                                </td>
                                                <td>
                                                    <t t-if="pattern.efficiency < 60">
                                                        <small class="text-danger">Optimisation requise</small>
                                                    </t>
                                                    <t t-elif="pattern.efficiency < 80">
                                                        <small class="text-warning">Amélioration possible</small>
                                                    </t>
                                                    <t t-else="">
                                                        <small class="text-success">Performance optimale</small>
                                                    </t>
                                                </td>
                                            </tr>
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Trends Tab -->
            <div t-if="isTrendsTab">
                <div class="row mb-4">
                    <div class="col-12">
                        <h4>Analyse des Tendances</h4>
                        <p class="text-muted">Évolution des métriques dans le temps</p>
                    </div>
                </div>

                <!-- Waiting Time Trends -->
                <div class="row mb-4">
                    <div class="col-md-8">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="card-title mb-0">Évolution des Temps d'Attente</h5>
                            </div>
                            <div class="card-body">
                                <canvas id="waitingTrendsChart" style="height: 300px;"></canvas>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="card-title mb-0">Analyse des Temps d'Attente</h5>
                            </div>
                            <div class="card-body">
                                <div class="mb-3">
                                    <small class="text-muted">Temps Actuel</small>
                                    <div class="h4" t-esc="formatDuration(reportData.trend_analysis.waiting_time_trends.current_avg)"/>
                                </div>
                                <div class="mb-3">
                                    <small class="text-muted">Statut</small>
                                    <div>
                                        <span class="badge"
                                              t-att-class="reportData.trend_analysis.waiting_time_trends.status === 'excellent' ? 'badge-success' : reportData.trend_analysis.waiting_time_trends.status === 'good' ? 'badge-warning' : 'badge-danger'">
                                            <t t-esc="reportData.trend_analysis.waiting_time_trends.status"/>
                                        </span>
                                    </div>
                                </div>
                                <div t-if="reportData.trend_analysis.waiting_time_trends.target_improvement > 0">
                                    <small class="text-muted">Amélioration Cible</small>
                                    <div class="text-info">
                                        -<t t-esc="formatDuration(reportData.trend_analysis.waiting_time_trends.target_improvement)"/>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Daily Trends -->
                <div class="row">
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="card-title mb-0">Tendance Quotidienne</h5>
                            </div>
                            <div class="card-body text-center">
                                <div class="mb-3">
                                    <i t-att-class="'fa fa-3x ' + (reportData.trend_analysis.daily_trend.trend === 'increasing' ? 'fa-arrow-up text-success' : reportData.trend_analysis.daily_trend.trend === 'decreasing' ? 'fa-arrow-down text-danger' : 'fa-arrows-h text-warning')"/>
                                </div>
                                <h4>
                                    <t t-if="reportData.trend_analysis.daily_trend.trend === 'increasing'">En Hausse</t>
                                    <t t-elif="reportData.trend_analysis.daily_trend.trend === 'decreasing'">En Baisse</t>
                                    <t t-else="">Stable</t>
                                </h4>
                                <p class="text-muted">
                                    Variation: <strong t-esc="reportData.trend_analysis.daily_trend.change_percentage + '%'"/>
                                </p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="card-title mb-0">Données Historiques</h5>
                            </div>
                            <div class="card-body">
                                <p><strong t-esc="reportData.historical_data.length"/> points de données</strong></p>
                                <p class="text-muted">
                                    Période: Dernières <t t-esc="Math.min(reportData.historical_data.length, 24)"/> heures
                                </p>
                                <div class="progress mb-2">
                                    <div class="progress-bar bg-info" 
                                         style="width: 100%"
                                         t-esc="'Couverture: 100%'">
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Recommendations Tab -->
            <div t-if="isRecommendationsTab">
                <div class="row mb-4">
                    <div class="col-12">
                        <h4>Recommandations</h4>
                        <p class="text-muted">Suggestions d'amélioration basées sur l'analyse des données</p>
                    </div>
                </div>

                <!-- Recommendations List -->
                <div class="row">
                    <div class="col-12">
                        <div t-if="!reportData.recommendations.length" class="alert alert-success">
                            <h4 class="alert-heading">
                                <i class="fa fa-thumbs-up"/> Excellente Performance !
                            </h4>
                            <p>Aucune recommandation spécifique à ce moment. Votre système fonctionne de manière optimale.</p>
                        </div>
                        
                        <div t-else="">
                            <div t-foreach="reportData.recommendations" 
                                 t-as="recommendation" 
                                 t-key="recommendation.type"
                                 class="card mb-3">
                                <div class="card-header"
                                     t-att-class="recommendation.priority === 'high' ? 'bg-danger text-white' : recommendation.priority === 'medium' ? 'bg-warning' : 'bg-info text-white'">
                                    <h5 class="card-title mb-0">
                                        <i t-att-class="'fa ' + getRecommendationIcon(recommendation.type)"/>
                                        Recommandation - 
                                        <span class="badge badge-light ms-2" t-esc="recommendation.priority"/>
                                    </h5>
                                </div>
                                <div class="card-body">
                                    <p class="card-text" t-esc="recommendation.message"/>
                                    
                                    <!-- Additional details based on type -->
                                    <div t-if="recommendation.type === 'capacity' and recommendation.affected_services">
                                        <hr/>
                                        <h6>Services Concernés:</h6>
                                        <div class="d-flex flex-wrap gap-1">
                                            <span t-foreach="recommendation.affected_services" 
                                                  t-as="service" 
                                                  t-key="service"
                                                  class="badge badge-secondary me-1 mb-1" 
                                                  t-esc="service"/>
                                        </div>
                                    </div>
                                    
                                    <div t-if="recommendation.type === 'efficiency'">
                                        <hr/>
                                        <div class="row">
                                            <div class="col-6">
                                                <small class="text-muted">Temps Actuel</small>
                                                <div class="fw-bold text-warning" t-esc="formatDuration(recommendation.current_avg)"/>
                                            </div>
                                            <div class="col-6">
                                                <small class="text-muted">Objectif</small>
                                                <div class="fw-bold text-success" t-esc="formatDuration(recommendation.target_avg)"/>
                                            </div>
                                        </div>
                                    </div>
                                    
                                    <div t-if="recommendation.type === 'retention'">
                                        <hr/>
                                        <p class="text-warning">
                                            <i class="fa fa-exclamation-circle"/>
                                            Taux d'abandon: <strong t-esc="recommendation.cancelled_rate + '%'"/>
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Action Plan -->
                <div class="row mt-4">
                    <div class="col-12">
                        <div class="card">
                            <div class="card-header">
                                <h5 class="card-title mb-0">Plan d'Action Suggéré</h5>
                            </div>
                            <div class="card-body">
                                <div class="timeline">
                                    <div class="timeline-item mb-3">
                                        <div class="timeline-marker bg-primary"></div>
                                        <div class="timeline-content">
                                            <h6>Court Terme (1-7 jours)</h6>
                                            <ul class="list-unstyled">
                                                <li t-foreach="reportData.recommendations.filter(r => r.priority === 'high')" 
                                                    t-as="rec" 
                                                    t-key="rec.type">
                                                    <i class="fa fa-check-square-o text-danger"/> <t t-esc="rec.message"/>
                                                </li>
                                                <li t-if="!reportData.recommendations.some(r => r.priority === 'high')">
                                                    <i class="fa fa-check text-success"/> Aucune action critique requise
                                                </li>
                                            </ul>
                                        </div>
                                    </div>
                                    <div class="timeline-item mb-3">
                                        <div class="timeline-marker bg-warning"></div>
                                        <div class="timeline-content">
                                            <h6>Moyen Terme (1-4 semaines)</h6>
                                            <ul class="list-unstyled">
                                                <li t-foreach="reportData.recommendations.filter(r => r.priority === 'medium')" 
                                                    t-as="rec" 
                                                    t-key="rec.type">
                                                    <i class="fa fa-square-o text-warning"/> <t t-esc="rec.message"/>
                                                </li>
                                                <li t-if="!reportData.recommendations.some(r => r.priority === 'medium')">
                                                    <i class="fa fa-check text-success"/> Optimisations continues recommandées
                                                </li>
                                            </ul>
                                        </div>
                                    </div>
                                    <div class="timeline-item">
                                        <div class="timeline-marker bg-info"></div>
                                        <div class="timeline-content">
                                            <h6>Long Terme (1-3 mois)</h6>
                                            <ul class="list-unstyled">
                                                <li><i class="fa fa-square-o text-info"/> Analyse des patterns saisonniers</li>
                                                <li><i class="fa fa-square-o text-info"/> Optimisation des processus métier</li>
                                                <li><i class="fa fa-square-o text-info"/> Formation du personnel</li>
                                            </ul>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>`;

// Enregistrer le composant
registry.category("actions").add("queue_dashboard_reports", QueueDashboardReports);

export { QueueDashboardReports };