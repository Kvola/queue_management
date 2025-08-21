/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { DashboardChartsFixes } from "./dashboard_charts_mixin";


class QueueDashboard extends Component {
    static template = "queue_management.QueueDashboardMain";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        // References pour les graphiques
        this.servicesChartRef = useRef("servicesChart");
        this.statsChartRef = useRef("statsChart");
        this.waitingTimeChartRef = useRef("waitingTimeChart");
        this.performanceChartRef = useRef("performanceChart");

        // Chart.js instance reference
        this.Chart = null;

        // Instances Chart.js
        this.charts = {
            services: null,
            stats: null,
            waitingTime: null,
            performance: null
        };

        this.state = useState({
            dashboardData: {
                services: [],
                waiting_tickets: [],
                serving_tickets: [],
                stats: {},
                historical_data: []
            },
            isLoading: true,
            lastUpdate: null,
            autoRefresh: true,
            connectionError: false,
            retryAttempts: 0,
            operationInProgress: new Set(),
            chartsEnabled: true,
            chartsInitialized: false,
            chartLibraryLoaded: false,
            chartsCreationInProgress: false  // Nouveau flag pour éviter les créations multiples
        });

        this.refreshInterval = null;
        this.retryTimeout = null;
        this.MAX_RETRY_ATTEMPTS = 3;
        this.RETRY_DELAY_BASE = 2000;
        this.REFRESH_INTERVAL = 15000;
        this.REQUEST_TIMEOUT = 30000;

        // Bind methods to preserve context
        this.handleVisibilityChange = this.handleVisibilityChange.bind(this);
        this.handleOnlineStatus = this.handleOnlineStatus.bind(this);
        this.handleWindowResize = this.handleWindowResize.bind(this);

        onWillStart(async () => {
            await this.initializeDashboard();
        });

        onMounted(() => {
            this.setupEventListeners();
            this.setupAutoRefresh();
            // Charger Chart.js et initialiser les graphiques
            this.loadChartLibraryAndInit();
            window.addEventListener('resize', this.handleWindowResize);
        });

        onWillUnmount(() => {
            this.cleanup();
            this.destroyAllCharts();
            window.removeEventListener('resize', this.handleWindowResize);
        });
    }

    // async loadBootstrap() {
    //     if (window.bootstrap) return;

    //     return new Promise((resolve, reject) => {
    //         const script = document.createElement("script");
    //         script.src = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js";
    //         script.onload = () => resolve();
    //         script.onerror = () => reject(new Error("Failed to load Bootstrap"));
    //         document.head.appendChild(script);
    //     });
    // }

    // Ajoutez ces méthodes à votre classe QueueDashboard

    // ========== MÉTHODES DU MENU DASHBOARD ==========

    /**
     * Affiche la fenêtre des rapports
     */
    async onShowReports(ev) {
        ev.preventDefault();

        try {
            // Générer les données du rapport
            const reportData = await this.generateReportData();

            // Ouvrir une action Odoo pour afficher le rapport
            return {
                type: 'ir.actions.client',
                tag: 'queue_dashboard_reports',
                name: 'Rapports Queue Management',
                context: {
                    'default_report_data': reportData,
                    'dashboard_data': this.state.dashboardData
                },
                target: 'new'
            };
        } catch (error) {
            console.error("Error showing reports:", error);
            this.notification.add(`Erreur lors de l'affichage des rapports: ${this.getErrorMessage(error)}`, {
                type: "danger"
            });
        }
    }

    /**
     * Exporte les données du dashboard
     */
    async onExportData(ev) {
        ev.preventDefault();

        try {
            // Créer un menu contextuel pour choisir le format d'export
            this.showExportModal();
            //this.showExportModalWithChartsOption
        } catch (error) {
            console.error("Error exporting data:", error);
            this.notification.add(`Erreur lors de l'export: ${this.getErrorMessage(error)}`, {
                type: "danger"
            });
        }
    }

    /**
     * Affiche la modal d'export
     */
    async showExportModal() {
        // Créer une modal Bootstrap dynamiquement
        const modalHtml = `
            <div class="modal fade" id="exportModal" tabindex="-1" aria-labelledby="exportModalLabel" aria-hidden="true">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="exportModalLabel">Exporter les données</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <p>Choisissez le format d'export :</p>
                            <div class="list-group">
                                <button type="button" class="list-group-item list-group-item-action" data-format="csv">
                                    <i class="fa fa-file-text-o"></i> CSV (Comma Separated Values)
                                </button>
                                <button type="button" class="list-group-item list-group-item-action" data-format="excel">
                                    <i class="fa fa-file-excel-o"></i> Excel (.xlsx)
                                </button>
                                <button type="button" class="list-group-item list-group-item-action" data-format="json">
                                    <i class="fa fa-file-code-o"></i> JSON
                                </button>
                                <button type="button" class="list-group-item list-group-item-action" data-format="pdf">
                                    <i class="fa fa-file-pdf-o"></i> PDF (Rapport)
                                </button>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Annuler</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Ajouter la modal au DOM
        const modalContainer = document.createElement('div');
        modalContainer.innerHTML = modalHtml;
        document.body.appendChild(modalContainer);


        // Initialiser la modal Bootstrap
        const modalElement = document.getElementById('exportModal');

        await this.loadBootstrap();
        const modal = new bootstrap.Modal(modalElement);

        // Ajouter les événements pour les boutons de format
        modalElement.querySelectorAll('[data-format]').forEach(button => {
            button.addEventListener('click', (e) => {
                const format = e.currentTarget.getAttribute('data-format');
                this.exportDataInFormat(format);
                modal.hide();
            });
        });

        // Nettoyer la modal après fermeture
        modalElement.addEventListener('hidden.bs.modal', () => {
            document.body.removeChild(modalContainer);
        });

        modal.show();
    }

    /**
     * Affiche une option pour inclure les graphiques dans l'export
     */
    /**
     * Affiche la modal d'export avec option pour inclure les graphiques
     */
    async showExportModalWithChartsOption() {
        const chartsAvailable = this.areChartsAvailableForExport();
        
        const modalHtml = `
            <div class="modal fade" id="exportModal" tabindex="-1" aria-labelledby="exportModalLabel" aria-hidden="true">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header bg-primary text-white">
                            <h5 class="modal-title" id="exportModalLabel">
                                <i class="fa fa-download me-2"></i>Exporter les données
                            </h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <div class="row">
                                <div class="col-md-6">
                                    <h6 class="text-primary mb-3">
                                        <i class="fa fa-cog me-2"></i>Options d'export
                                    </h6>
                                    
                                    ${chartsAvailable ? `
                                    <div class="card mb-4">
                                        <div class="card-body">
                                            <div class="form-check form-switch">
                                                <input class="form-check-input" type="checkbox" id="includeCharts" checked style="transform: scale(1.2);">
                                                <label class="form-check-label fw-bold" for="includeCharts">
                                                    <i class="fa fa-bar-chart me-2 text-success"></i>Inclure les graphiques
                                                </label>
                                            </div>
                                            <small class="text-muted d-block mt-2">
                                                Les graphiques actuels seront capturés et inclus dans l'export PDF
                                            </small>
                                        </div>
                                    </div>
                                    ` : `
                                    <div class="alert alert-warning mb-4">
                                        <i class="fa fa-exclamation-triangle me-2"></i>
                                        <strong>Graphiques non disponibles</strong>
                                        <p class="mb-0 mt-1 small">Les graphiques ne sont pas actuellement disponibles pour l'export.</p>
                                    </div>
                                    `}
                                    
                                    <div class="card">
                                        <div class="card-body">
                                            <h6 class="card-title">
                                                <i class="fa fa-info-circle me-2 text-info"></i>Nom du fichier
                                            </h6>
                                            <div class="input-group input-group-sm">
                                                <span class="input-group-text">dashboard_</span>
                                                <input type="text" id="exportFilename" class="form-control" value="${new Date().toISOString().slice(0, 10)}">
                                                <span class="input-group-text">.ext</span>
                                            </div>
                                            <small class="text-muted d-block mt-2">
                                                Le nom sera adapté automatiquement au format choisi
                                            </small>
                                        </div>
                                    </div>
                                </div>
                                
                                <div class="col-md-6">
                                    <h6 class="text-primary mb-3">
                                        <i class="fa fa-file me-2"></i>Formats disponibles
                                    </h6>
                                    
                                    <div class="list-group">
                                        <button type="button" class="list-group-item list-group-item-action d-flex align-items-center" data-format="pdf">
                                            <span class="badge bg-danger me-3">
                                                <i class="fa fa-file-pdf-o fa-lg"></i>
                                            </span>
                                            <div class="flex-grow-1">
                                                <h6 class="mb-1">PDF Document</h6>
                                                <small class="text-muted">Rapport complet avec mise en page</small>
                                            </div>
                                            <i class="fa fa-chevron-right text-muted"></i>
                                        </button>
                                        
                                        <button type="button" class="list-group-item list-group-item-action d-flex align-items-center" data-format="excel">
                                            <span class="badge bg-success me-3">
                                                <i class="fa fa-file-excel-o fa-lg"></i>
                                            </span>
                                            <div class="flex-grow-1">
                                                <h6 class="mb-1">Excel Workbook</h6>
                                                <small class="text-muted">Données structurées pour analyse</small>
                                            </div>
                                            <i class="fa fa-chevron-right text-muted"></i>
                                        </button>
                                        
                                        <button type="button" class="list-group-item list-group-item-action d-flex align-items-center" data-format="csv">
                                            <span class="badge bg-info me-3">
                                                <i class="fa fa-file-text-o fa-lg"></i>
                                            </span>
                                            <div class="flex-grow-1">
                                                <h6 class="mb-1">CSV File</h6>
                                                <small class="text-muted">Format texte compatible universel</small>
                                            </div>
                                            <i class="fa fa-chevron-right text-muted"></i>
                                        </button>
                                        
                                        <button type="button" class="list-group-item list-group-item-action d-flex align-items-center" data-format="json">
                                            <span class="badge bg-warning me-3">
                                                <i class="fa fa-file-code-o fa-lg"></i>
                                            </span>
                                            <div class="flex-grow-1">
                                                <h6 class="mb-1">JSON Data</h6>
                                                <small class="text-muted">Données brutes pour développeurs</small>
                                            </div>
                                            <i class="fa fa-chevron-right text-muted"></i>
                                        </button>
                                    </div>
                                    
                                    ${chartsAvailable ? `
                                    <div class="alert alert-info mt-3">
                                        <i class="fa fa-lightbulb-o me-2"></i>
                                        <small>Les graphiques sont disponibles pour l'export PDF uniquement</small>
                                    </div>
                                    ` : ''}
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">
                                <i class="fa fa-times me-2"></i>Annuler
                            </button>
                            <button type="button" class="btn btn-primary" id="startExportBtn" disabled>
                                <i class="fa fa-download me-2"></i>Commencer l'export
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Ajouter la modal au DOM
        const modalContainer = document.createElement('div');
        modalContainer.innerHTML = modalHtml;
        document.body.appendChild(modalContainer);

        try {
            // Initialiser Bootstrap
            await this.loadBootstrap();
            const modalElement = document.getElementById('exportModal');
            const modal = new bootstrap.Modal(modalElement);

            // Références aux éléments de la modal
            const includeChartsCheckbox = document.getElementById('includeCharts');
            const filenameInput = document.getElementById('exportFilename');
            const startExportBtn = document.getElementById('startExportBtn');
            const formatButtons = modalElement.querySelectorAll('[data-format]');

            let selectedFormat = null;

            // Gérer la sélection du format
            formatButtons.forEach(button => {
                button.addEventListener('click', (e) => {
                    // Désélectionner tous les boutons
                    formatButtons.forEach(btn => {
                        btn.classList.remove('active', 'border-primary');
                        btn.style.backgroundColor = '';
                    });

                    // Sélectionner le bouton cliqué
                    e.currentTarget.classList.add('active', 'border-primary');
                    e.currentTarget.style.backgroundColor = '#f8f9fa';
                    
                    selectedFormat = e.currentTarget.getAttribute('data-format');
                    startExportBtn.disabled = false;

                    // Adapter l'interface en fonction du format
                    this.updateModalForFormat(selectedFormat, includeChartsCheckbox);
                });
            });

            // Mettre à jour l'interface selon le format
            const updateModalForFormat = (format, chartsCheckbox) => {
                if (format !== 'pdf' && chartsCheckbox) {
                    chartsCheckbox.disabled = true;
                    chartsCheckbox.checked = false;
                    const chartsLabel = chartsCheckbox.closest('.form-check');
                    if (chartsLabel) {
                        chartsLabel.style.opacity = '0.6';
                    }
                } else if (chartsCheckbox) {
                    chartsCheckbox.disabled = false;
                    const chartsLabel = chartsCheckbox.closest('.form-check');
                    if (chartsLabel) {
                        chartsLabel.style.opacity = '1';
                    }
                }
            };

            // Gérer le clic sur le bouton d'export
            startExportBtn.addEventListener('click', async () => {
                if (!selectedFormat) return;

                const includeCharts = includeChartsCheckbox ? includeChartsCheckbox.checked : false;
                const customFilename = filenameInput ? filenameInput.value : '';
                
                modal.hide();
                
                // Préparer le nom de fichier
                let filename = customFilename || `dashboard_${new Date().toISOString().slice(0, 10)}`;
                filename = `${filename}.${selectedFormat}`;

                try {
                    const exportData = this.prepareExportData();
                    
                    switch (selectedFormat) {
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
                    }

                    this.notification.add(`Export ${selectedFormat.toUpperCase()} généré avec succès`, {
                        type: "success"
                    });

                } catch (error) {
                    console.error("Export error:", error);
                    this.notification.add(`Erreur lors de l'export: ${this.getErrorMessage(error)}`, {
                        type: "danger"
                    });
                }
            });

            // Nettoyer la modal après fermeture
            modalElement.addEventListener('hidden.bs.modal', () => {
                setTimeout(() => {
                    if (document.body.contains(modalContainer)) {
                        document.body.removeChild(modalContainer);
                    }
                }, 500);
            });

            // Gérer la fermeture via Escape
            modalElement.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    modal.hide();
                }
            });

            // Afficher la modal
            modal.show();

            // Focus sur le premier élément
            setTimeout(() => {
                if (formatButtons.length > 0) {
                    formatButtons[0].focus();
                }
            }, 100);

        } catch (error) {
            console.error("Error showing export modal:", error);
            
            // Nettoyer en cas d'erreur
            if (document.body.contains(modalContainer)) {
                document.body.removeChild(modalContainer);
            }
            
            this.notification.add("Erreur lors de l'ouverture de la modal d'export", {
                type: "danger"
            });
        }
    }

    /**
     * Met à jour l'interface en fonction du format sélectionné
     */
    updateModalForFormat(format, chartsCheckbox) {
        if (!chartsCheckbox) return;

        const chartsLabel = chartsCheckbox.closest('.form-check');
        if (!chartsLabel) return;

        if (format !== 'pdf') {
            chartsCheckbox.disabled = true;
            chartsCheckbox.checked = false;
            chartsLabel.style.opacity = '0.6';
            chartsLabel.title = 'Graphiques disponibles uniquement pour le format PDF';
        } else {
            chartsCheckbox.disabled = false;
            chartsLabel.style.opacity = '1';
            chartsLabel.title = '';
        }
    }

    /**
     * Charge Bootstrap si nécessaire
     */
    async loadBootstrap() {
        if (typeof bootstrap !== 'undefined' && typeof bootstrap.Modal !== 'undefined') {
            return true;
        }

        return new Promise((resolve, reject) => {
            if (typeof bootstrap !== 'undefined') {
                resolve();
                return;
            }

            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js';
            script.integrity = 'sha384-C6RzsynM9kWDrMNeT87bh95OGNyZPhcTNXj1NW7RuBCsyN/o0jlpcV8Qyq46cDfL';
            script.crossOrigin = 'anonymous';
            
            script.onload = () => resolve();
            script.onerror = () => reject(new Error('Failed to load Bootstrap'));
            
            document.head.appendChild(script);
        });
    }

    /**
     * Exporte les données dans le format spécifié
     */
    async exportDataInFormat(format) {
        try {
            const exportData = this.prepareExportData();
            const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-');

            switch (format) {
                case 'csv':
                    this.exportToCSV(exportData, `dashboard_data_${timestamp}.csv`);
                    break;
                case 'excel':
                    await this.exportToExcel(exportData, `dashboard_data_${timestamp}.xlsx`);
                    break;
                case 'json':
                    this.exportToJSON(exportData, `dashboard_data_${timestamp}.json`);
                    break;
                case 'pdf':
                    // Utiliser la nouvelle méthode côté client
                    await this.exportToPDF(exportData, `dashboard_report_${timestamp}.pdf`);
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

    /**
     * Prépare les données pour l'export
     */
    prepareExportData() {
        return {
            metadata: {
                generated_at: new Date().toISOString(),
                dashboard_version: '1.0',
                total_records: this.calculateTotalRecords()
            },
            summary: {
                total_tickets: this.stats.total_tickets,
                waiting_tickets: this.stats.waiting_tickets,
                serving_tickets: this.stats.serving_tickets,
                completed_tickets: this.stats.completed_tickets,
                cancelled_tickets: this.stats.cancelled_tickets,
                no_show_tickets: this.stats.no_show_tickets,
                average_wait_time: this.stats.average_wait_time,
                completion_rate: this.stats.completion_rate,
                active_services: this.stats.active_services,
                total_services: this.stats.total_services
            },
            services: this.dashboardData.services.map(service => ({
                id: service.id,
                name: service.name,
                is_open: service.is_open,
                waiting_count: service.waiting_count,
                serving_count: service.serving_count,
                served_count: service.served_count,
                total_tickets_today: service.total_tickets_today,
                avg_waiting_time: service.avg_waiting_time,
                capacity_percentage: service.capacity_percentage
            })),
            waiting_tickets: this.dashboardData.waiting_tickets.map(ticket => ({
                id: ticket.id,
                number: ticket.number,
                service_name: ticket.service_name,
                customer_name: ticket.customer_name,
                created_time: ticket.created_time,
                priority: ticket.priority,
                position_in_queue: ticket.position_in_queue,
                estimated_wait: ticket.estimated_wait
            })),
            serving_tickets: this.dashboardData.serving_tickets.map(ticket => ({
                id: ticket.id,
                number: ticket.number,
                service_name: ticket.service_name,
                customer_name: ticket.customer_name,
                created_time: ticket.created_time,
                served_time: ticket.served_time,
                agent_name: ticket.agent_name,
                service_duration: ticket.service_duration
            })),
            historical_data: this.dashboardData.historical_data
        };
    }

    /**
     * Export en CSV
     */
    exportToCSV(data, filename) {
        const csvContent = this.convertToCSV(data);
        this.downloadFile(csvContent, filename, 'text/csv');
    }

    /**
     * Convertit les données en format CSV
     */
    convertToCSV(data) {
        let csv = '';

        // En-tête des statistiques générales
        csv += 'STATISTIQUES GENERALES\n';
        csv += 'Métrique,Valeur\n';
        Object.entries(data.summary).forEach(([key, value]) => {
            csv += `${this.formatCSVHeader(key)},${value}\n`;
        });
        csv += '\n';

        // Services
        csv += 'SERVICES\n';
        if (data.services.length > 0) {
            const serviceHeaders = Object.keys(data.services[0]);
            csv += serviceHeaders.map(h => this.formatCSVHeader(h)).join(',') + '\n';
            data.services.forEach(service => {
                csv += serviceHeaders.map(h => this.escapeCSV(service[h])).join(',') + '\n';
            });
        }
        csv += '\n';

        // Tickets en attente
        csv += 'TICKETS EN ATTENTE\n';
        if (data.waiting_tickets.length > 0) {
            const waitingHeaders = Object.keys(data.waiting_tickets[0]);
            csv += waitingHeaders.map(h => this.formatCSVHeader(h)).join(',') + '\n';
            data.waiting_tickets.forEach(ticket => {
                csv += waitingHeaders.map(h => this.escapeCSV(ticket[h])).join(',') + '\n';
            });
        }
        csv += '\n';

        // Tickets en service
        csv += 'TICKETS EN SERVICE\n';
        if (data.serving_tickets.length > 0) {
            const servingHeaders = Object.keys(data.serving_tickets[0]);
            csv += servingHeaders.map(h => this.formatCSVHeader(h)).join(',') + '\n';
            data.serving_tickets.forEach(ticket => {
                csv += servingHeaders.map(h => this.escapeCSV(ticket[h])).join(',') + '\n';
            });
        }

        return csv;
    }

    /**
     * Export en Excel (nécessite une approche serveur)
     */
    async exportToExcel(data, filename) {
        try {
            // Appeler le serveur pour générer le fichier Excel
            const result = await this.orm.call("queue.service", "generate_excel_export", [data]);

            if (result.file_content) {
                // Décoder le contenu base64 et télécharger
                const binaryString = atob(result.file_content);
                const bytes = new Uint8Array(binaryString.length);
                for (let i = 0; i < binaryString.length; i++) {
                    bytes[i] = binaryString.charCodeAt(i);
                }
                const blob = new Blob([bytes], {
                    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                });
                this.downloadBlob(blob, filename);
            } else {
                throw new Error('Erreur lors de la génération du fichier Excel');
            }
        } catch (error) {
            console.error("Excel export error:", error);
            // Fallback vers CSV si Excel échoue
            this.notification.add("Export Excel non disponible, export CSV généré à la place", {
                type: "warning"
            });
            this.exportToCSV(data, filename.replace('.xlsx', '.csv'));
        }
    }

    /**
     * Export en JSON
     */
    exportToJSON(data, filename) {
        const jsonContent = JSON.stringify(data, null, 2);
        this.downloadFile(jsonContent, filename, 'application/json');
    }

    /**
     * Export en PDF - Version côté client avec jsPDF
     */
    async exportToPDF(data, filename) {
        // Validation des paramètres
        if (!data) {
            console.error("PDF export error: No data provided");
            this.notification.add("Aucune donnée à exporter", { type: "danger" });
            return false;
        }

        if (!filename || !filename.trim()) {
            filename = `export_${new Date().toISOString().slice(0, 10)}.pdf`;
        } else if (!filename.endsWith('.pdf')) {
            filename = filename.replace(/\.[^/.]+$/, '') + '.pdf';
        }

        try {
            console.log('Starting PDF export...');
            
            // Charger jsPDF dynamiquement
            const jsPDFLoaded = await this.loadJsPDFLibrary();
            if (!jsPDFLoaded) {
                throw new Error('Failed to load jsPDF library');
            }
            
            // Créer le document PDF
            const doc = await this.createPDFDocument(data);
            if (!doc) {
                throw new Error('Failed to create PDF document');
            }
            
            // Générer et télécharger le PDF
            doc.save(filename);
            
            this.notification.add("Export PDF terminé avec succès", { type: "success" });
            console.log(`PDF exported successfully: ${filename}`);
            return true;
            
        } catch (error) {
            console.error("PDF export error:", error);
            
            // Tentative d'export serveur si disponible
            try {
                console.log('Trying server-side PDF export...');
                const serverResult = await this.exportToPDFServer(data, filename);
                
                if (serverResult) {
                    this.notification.add("Export PDF terminé via le serveur", { type: "success" });
                    return true;
                }
            } catch (serverError) {
                console.error("Server PDF export failed:", serverError);
            }
            
            // Fallback vers JSON en dernier recours
            return this.handlePDFExportFallback(data, filename);
        }
    }

    /**
     * Charge la bibliothèque jsPDF dynamiquement
     * @returns {Promise<boolean>} - true si le chargement a réussi
     */
    async loadJsPDFLibrary() {
        try {
            // Vérifier si jsPDF est déjà chargé (différentes versions)
            if ((window.jspdf && window.jspdf.jsPDF) || window.jsPDF) {
                return true;
            }

            // Charger jsPDF via CDN
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js';
            
            return new Promise((resolve, reject) => {
                script.onload = () => {
                    // Vérifier que la bibliothèque est bien disponible
                    setTimeout(() => {
                        if ((window.jspdf && window.jspdf.jsPDF) || window.jsPDF) {
                            resolve(true);
                        } else {
                            reject(new Error('jsPDF not available after loading'));
                        }
                    }, 100);
                };
                
                script.onerror = () => reject(new Error('Failed to load jsPDF script'));
                
                // Timeout de 10 secondes
                setTimeout(() => reject(new Error('jsPDF loading timeout')), 10000);
                
                document.head.appendChild(script);
            });
            
        } catch (error) {
            console.error('Error loading jsPDF:', error);
            return false;
        }
    }

    /**
     * Crée le document PDF à partir des données du dashboard
     * @param {Object} data - Les données à inclure dans le PDF
     * @returns {Promise<Object>} - L'instance du document jsPDF
     */
    async createPDFDocument(data) {
        try {
            // Utiliser la bonne référence à jsPDF
            const jsPDF = window.jspdf && window.jspdf.jsPDF ? window.jspdf.jsPDF : window.jsPDF;
            const doc = new jsPDF();
            
            // Configuration de base
            const pageWidth = doc.internal.pageSize.getWidth();
            const pageHeight = doc.internal.pageSize.getHeight();
            const margin = 15;
            let yPosition = margin;
            
            // Titre du document
            doc.setFontSize(16);
            doc.setFont(undefined, 'bold');
            doc.text('Rapport Queue Management', pageWidth / 2, yPosition, { align: 'center' });
            yPosition += 10;
            
            // Date d'export
            doc.setFontSize(10);
            doc.setFont(undefined, 'normal');
            doc.text(`Généré le: ${new Date().toLocaleString('fr-FR')}`, margin, yPosition);
            yPosition += 15;
            
            // Statistiques générales
            yPosition = this.addStatsToPDF(doc, data.summary, yPosition, margin, pageWidth, pageHeight);
            
            // Services
            yPosition += 10;
            yPosition = this.addServicesToPDF(doc, data.services, yPosition, margin, pageWidth, pageHeight);
            
            // Tickets en attente (limités pour éviter les PDF trop longs)
            if (data.waiting_tickets && data.waiting_tickets.length > 0) {
                if (yPosition > pageHeight - 50) {
                    doc.addPage();
                    yPosition = margin;
                }
                yPosition += 10;
                yPosition = this.addTicketsToPDF(doc, data.waiting_tickets.slice(0, 10), "Tickets en Attente", yPosition, margin, pageWidth, pageHeight);
            }
            
            return doc;
            
        } catch (error) {
            console.error('Error creating PDF document:', error);
            throw error;
        }
    }

    /**
     * Ajoute les tickets au PDF
     */
    addTicketsToPDF(doc, tickets, title, yPosition, margin, pageWidth, pageHeight) {
        if (!tickets || tickets.length === 0) {
            return yPosition;
        }
        
        if (yPosition > pageHeight - 50) {
            doc.addPage();
            yPosition = margin;
        }
        
        doc.setFontSize(12);
        doc.setFont(undefined, 'bold');
        doc.text(`${title} (${tickets.length}):`, margin, yPosition);
        yPosition += 8;
        
        doc.setFontSize(10);
        doc.setFont(undefined, 'normal');
        
        tickets.forEach(ticket => {
            if (yPosition > pageHeight - 30) {
                doc.addPage();
                yPosition = margin;
            }
            
            doc.text(`Ticket #${ticket.number} - ${ticket.service_name}`, margin, yPosition);
            yPosition += 5;
            doc.text(`Client: ${ticket.customer_name}`, margin, yPosition);
            yPosition += 5;
            
            if (ticket.position_in_queue) {
                doc.text(`Position: ${ticket.position_in_queue}`, margin, yPosition);
                yPosition += 5;
            }
            
            if (ticket.estimated_wait) {
                doc.text(`Attente estimée: ${ticket.estimated_wait} min`, margin, yPosition);
                yPosition += 5;
            }
            
            yPosition += 3; // Espacement entre les tickets
        });
        
        return yPosition;
    }

    /**
     * Gère le fallback vers l'export JSON si PDF échoue
     */
    handlePDFExportFallback(data, filename) {
        try {
            const jsonFilename = filename.replace('.pdf', '.json');
            const jsonData = JSON.stringify(data, null, 2);
            
            // Utiliser la méthode existante ou créer un fallback
            if (typeof this.exportToJSON === 'function') {
                this.notification.add("Export PDF non disponible, export JSON généré à la place", { type: "warning" });
                this.exportToJSON(data, jsonFilename);
            } else {
                // Fallback basique pour l'export JSON
                const blob = new Blob([jsonData], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                
                const link = document.createElement('a');
                link.href = url;
                link.download = jsonFilename;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                URL.revokeObjectURL(url);
                
                this.notification.add("Export PDF non disponible, fichier JSON téléchargé", { type: "warning" });
            }
            
            return false; // Indique que l'export PDF a échoué mais qu'un fallback a été utilisé
            
        } catch (fallbackError) {
            console.error("Fallback export failed:", fallbackError);
            this.notification.add("Échec de l'export (PDF et JSON)", { type: "error" });
            return false;
        }
    }

    /**
     * Version serveur de l'export PDF (fallback)
     */
    async exportToPDFServer(data, filename) {
        try {
            const result = await this.orm.call("queue.service", "generate_pdf_report", [data]);

            if (result && result.file_content) {
                const binaryString = atob(result.file_content);
                const bytes = new Uint8Array(binaryString.length);
                for (let i = 0; i < binaryString.length; i++) {
                    bytes[i] = binaryString.charCodeAt(i);
                }
                const blob = new Blob([bytes], { type: 'application/pdf' });
                
                // Télécharger le blob
                const url = window.URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = filename;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                window.URL.revokeObjectURL(url);
                
                return true;
            }
            
            throw new Error('Erreur lors de la génération du PDF serveur');
            
        } catch (error) {
            console.error("Server PDF export error:", error);
            throw error;
        }
    }

    /**
     * Ajoute les statistiques au PDF
     */
    addStatsToPDF(doc, stats, yPosition, margin, pageWidth, pageHeight) {
        doc.setFontSize(12);
        doc.setFont(undefined, 'bold');
        doc.text('Statistiques Générales:', margin, yPosition);
        yPosition += 8;
        
        doc.setFontSize(10);
        doc.setFont(undefined, 'normal');
        
        const statsData = [
            ['Total Tickets', stats.total_tickets],
            ['Tickets Terminés', stats.completed_tickets],
            ['En Attente', stats.waiting_tickets],
            ['En Service', stats.serving_tickets],
            ['Annulés/Absents', (stats.cancelled_tickets || 0) + (stats.no_show_tickets || 0)],
            ['Temps d\'Attente Moyen', `${stats.average_wait_time} min`],
            ['Taux de Completion', `${stats.completion_rate}%`],
            ['Services Actifs', `${stats.active_services}/${stats.total_services}`]
        ];
        
        statsData.forEach(([label, value]) => {
            if (yPosition > pageHeight - 20) {
                doc.addPage();
                yPosition = margin;
            }
            
            doc.text(`${label}:`, margin, yPosition);
            doc.text(value.toString(), pageWidth - margin - doc.getTextWidth(value.toString()), yPosition, { align: 'right' });
            yPosition += 6;
        });
        
        return yPosition;
    }

    /**
     * Ajoute les services au PDF
     */
    addServicesToPDF(doc, services, yPosition, margin, pageWidth, pageHeight) {
        if (!services || services.length === 0) {
            return yPosition;
        }
        
        if (yPosition > pageHeight - 50) {
            doc.addPage();
            yPosition = margin;
        }
        
        doc.setFontSize(12);
        doc.setFont(undefined, 'bold');
        doc.text('Services:', margin, yPosition);
        yPosition += 8;
        
        doc.setFontSize(10);
        doc.setFont(undefined, 'normal');
        
        // En-tête du tableau
        doc.setFillColor(240, 240, 240);
        doc.rect(margin, yPosition, pageWidth - 2 * margin, 8, 'F');
        doc.setFont(undefined, 'bold');
        
        const colWidth = (pageWidth - 2 * margin) / 4;
        doc.text('Service', margin + 2, yPosition + 5);
        doc.text('Statut', margin + colWidth + 2, yPosition + 5);
        doc.text('Attente', margin + 2 * colWidth + 2, yPosition + 5);
        doc.text('Capacité', margin + 3 * colWidth + 2, yPosition + 5);
        
        yPosition += 8;
        doc.setFont(undefined, 'normal');
        
        // Données des services
        services.forEach(service => {
            if (yPosition > pageHeight - 20) {
                doc.addPage();
                yPosition = margin;
                
                // Réafficher l'en-tête sur la nouvelle page
                doc.setFillColor(240, 240, 240);
                doc.rect(margin, yPosition, pageWidth - 2 * margin, 8, 'F');
                doc.setFont(undefined, 'bold');
                doc.text('Service', margin + 2, yPosition + 5);
                doc.text('Statut', margin + colWidth + 2, yPosition + 5);
                doc.text('Attente', margin + 2 * colWidth + 2, yPosition + 5);
                doc.text('Capacité', margin + 3 * colWidth + 2, yPosition + 5);
                yPosition += 8;
                doc.setFont(undefined, 'normal');
            }
            
            const status = service.is_open ? 'Ouvert' : 'Fermé';
            const capacityColor = service.capacity_percentage > 80 ? [220, 53, 69] : 
                                service.capacity_percentage > 60 ? [255, 193, 7] : [40, 167, 69];
            
            doc.text(service.name.substring(0, 20), margin + 2, yPosition + 5);
            doc.text(status, margin + colWidth + 2, yPosition + 5);
            doc.text(service.waiting_count.toString(), margin + 2 * colWidth + 2, yPosition + 5);
            
            // Capacité avec couleur
            doc.setTextColor(...capacityColor);
            doc.text(`${service.capacity_percentage}%`, margin + 3 * colWidth + 2, yPosition + 5);
            doc.setTextColor(0, 0, 0); // Reset color
            
            yPosition += 6;
        });
        
        return yPosition;
    }

    /**
     * Ajoute un séparateur
     */
    addSeparator(doc, yPosition, pageWidth, margin) {
        doc.line(margin, yPosition, pageWidth - margin, yPosition);
        return yPosition + 5;
    }

    /**
     * Ajoute un titre de section
     */
    addSectionTitle(doc, title, yPosition, style) {
        doc.setFontSize(style.fontSize);
        doc.setFont(undefined, style.fontStyle);
        doc.text(title, margin, yPosition);
        return yPosition + 7;
    }

    
































    /**
     * Crée le document PDF avec les graphiques
     */
    async createPDFWithCharts(data) {
        try {
            // Capturer les graphiques avant de créer le PDF
            const chartImages = await this.captureAllCharts();
            
            const jsPDF = window.jspdf && window.jspdf.jsPDF ? window.jspdf.jsPDF : window.jsPDF;
            const doc = new jsPDF();
            
            const pageWidth = doc.internal.pageSize.getWidth();
            const pageHeight = doc.internal.pageSize.getHeight();
            const margin = 15;
            let yPosition = margin;
            
            // Titre
            doc.setFontSize(16);
            doc.setFont(undefined, 'bold');
            doc.text('Rapport Queue Management avec Graphiques', pageWidth / 2, yPosition, { align: 'center' });
            yPosition += 10;
            
            // Date
            doc.setFontSize(10);
            doc.setFont(undefined, 'normal');
            doc.text(`Généré le: ${new Date().toLocaleString('fr-FR')}`, margin, yPosition);
            yPosition += 15;
            
            // Ajouter les graphiques
            if (chartImages.length > 0) {
                yPosition = this.addChartsToPDF(doc, chartImages, yPosition, margin, pageWidth, pageHeight);
            }
            
            // Statistiques
            yPosition += 10;
            yPosition = this.addStatsToPDF(doc, data.summary, yPosition, margin, pageWidth, pageHeight);
            
            // Services
            yPosition += 10;
            yPosition = this.addServicesToPDF(doc, data.services, yPosition, margin, pageWidth, pageHeight);
            
            return doc;
            
        } catch (error) {
            console.error('Error creating PDF with charts:', error);
            throw error;
        }
    }

    /**
     * Ajoute les graphiques au PDF
     */
    addChartsToPDF(doc, chartImages, yPosition, margin, pageWidth, pageHeight) {
        doc.setFontSize(14);
        doc.setFont(undefined, 'bold');
        doc.text('Graphiques', margin, yPosition);
        yPosition += 10;
        
        doc.setFontSize(10);
        doc.setFont(undefined, 'normal');
        
        for (const chart of chartImages) {
            try {
                // Vérifier si on doit ajouter une nouvelle page
                if (yPosition > pageHeight - 150) {
                    doc.addPage();
                    yPosition = margin;
                }
                
                // Titre du graphique
                doc.setFont(undefined, 'bold');
                doc.text(chart.title, margin, yPosition);
                yPosition += 6;
                
                // Ajouter l'image du graphique
                const imgWidth = pageWidth - 2 * margin;
                const imgHeight = 100; // Hauteur fixe pour les graphiques
                
                doc.addImage(chart.image, 'PNG', margin, yPosition, imgWidth, imgHeight);
                yPosition += imgHeight + 10;
                
            } catch (error) {
                console.warn(`Failed to add chart ${chart.name} to PDF:`, error);
                // Continuer avec les graphiques suivants
            }
        }
        
        return yPosition;
    }

    /**
     * Vérifie si les graphiques sont disponibles pour l'export
     */
    areChartsAvailableForExport() {
        if (!this.state.chartsEnabled || !this.state.chartsInitialized) {
            return false;
        }
        
        // Vérifier qu'au moins un graphique est valide
        return Object.values(this.charts).some(chart => 
            chart && this.isChartValid(chart)
        );
    }








    






















    /**
     * Capture un graphique Canvas en image data URL
     * @param {HTMLCanvasElement} canvas - L'élément canvas à capturer
     * @returns {Promise<string>} - Data URL de l'image
     */
    async captureChartAsImage(canvas) {
        return new Promise((resolve, reject) => {
            try {
                if (!canvas) {
                    reject(new Error('Canvas element not found'));
                    return;
                }

                // Vérifier si le canvas a du contenu
                const context = canvas.getContext('2d');
                const imageData = context.getImageData(0, 0, canvas.width, canvas.height).data;
                let isEmpty = true;
                
                for (let i = 0; i < imageData.length; i += 4) {
                    if (imageData[i + 3] !== 0) { // Vérifier l'alpha channel
                        isEmpty = false;
                        break;
                    }
                }
                
                if (isEmpty) {
                    reject(new Error('Canvas is empty'));
                    return;
                }

                // Capturer le canvas en image
                canvas.toBlob((blob) => {
                    if (!blob) {
                        reject(new Error('Failed to capture canvas'));
                        return;
                    }
                    
                    const reader = new FileReader();
                    reader.onload = () => resolve(reader.result);
                    reader.onerror = () => reject(new Error('Failed to read blob'));
                    reader.readAsDataURL(blob);
                }, 'image/png', 1.0); // Qualité maximale
                
            } catch (error) {
                reject(error);
            }
        });
    }

    /**
     * Capture tous les graphiques visibles
     * @returns {Promise<Array>} - Tableau des images des graphiques
     */
    async captureAllCharts() {
        const charts = [];
        
        try {
            // Capturer chaque graphique
            for (const [chartName, chartInstance] of Object.entries(this.charts)) {
                if (chartInstance && this.isChartValid(chartInstance)) {
                    try {
                        const imageData = await this.captureChartAsImage(chartInstance.canvas);
                        charts.push({
                            name: chartName,
                            image: imageData,
                            title: this.getChartTitle(chartName)
                        });
                    } catch (error) {
                        console.warn(`Failed to capture ${chartName} chart:`, error);
                    }
                }
            }
        } catch (error) {
            console.error('Error capturing charts:', error);
        }
        
        return charts;
    }

    /**
     * Retourne le titre du graphique
     */
    getChartTitle(chartName) {
        const titles = {
            'services': 'État des Files par Service',
            'stats': 'Répartition des Tickets',
            'waitingTime': 'Temps d\'Attente par Service',
            'performance': 'Performance des Services'
        };
        return titles[chartName] || chartName;
    }

























    /**
     * Ajoute un tableau de statistiques
     */
    addStatsTable(doc, stats, yPosition, margin, contentWidth) {
        const rowHeight = 7;
        const col1Width = contentWidth * 0.6;
        const col2Width = contentWidth * 0.4;
        
        // En-tête du tableau
        doc.setFillColor(240, 240, 240);
        doc.rect(margin, yPosition, contentWidth, rowHeight, 'F');
        doc.setFontSize(10);
        doc.setFont(undefined, 'bold');
        doc.text('Métrique', margin + 2, yPosition + 5);
        doc.text('Valeur', margin + col1Width + 2, yPosition + 5);
        yPosition += rowHeight;
        
        // Données
        doc.setFont(undefined, 'normal');
        const statsData = [
            ['Total Tickets', stats.total_tickets],
            ['Tickets Terminés', stats.completed_tickets],
            ['En Attente', stats.waiting_tickets],
            ['En Service', stats.serving_tickets],
            ['Annulés/Absents', (stats.cancelled_tickets || 0) + (stats.no_show_tickets || 0)],
            ['Temps d\'Attente Moyen', `${stats.average_wait_time} min`],
            ['Taux de Completion', `${stats.completion_rate}%`],
            ['Services Actifs', `${stats.active_services}/${stats.total_services}`]
        ];
        
        statsData.forEach(([label, value]) => {
            if (yPosition > doc.internal.pageSize.getHeight() - 20) {
                doc.addPage();
                yPosition = margin;
            }
            
            doc.text(label, margin + 2, yPosition + 5);
            doc.text(value.toString(), margin + col1Width + 2, yPosition + 5);
            yPosition += rowHeight;
        });
        
        return yPosition + 3;
    }

    /**
     * Ajoute un tableau de services
     */
    addServicesTable(doc, services, yPosition, margin, contentWidth) {
        if (services.length === 0) {
            return this.addNoDataMessage(doc, yPosition);
        }
        
        const rowHeight = 7;
        const cols = [
            { header: 'Service', width: 0.4 },
            { header: 'Statut', width: 0.2 },
            { header: 'Attente', width: 0.2 },
            { header: 'Capacité', width: 0.2 }
        ];
        
        // En-tête
        doc.setFillColor(240, 240, 240);
        doc.rect(margin, yPosition, contentWidth, rowHeight, 'F');
        doc.setFontSize(9);
        doc.setFont(undefined, 'bold');
        
        let xPosition = margin + 2;
        cols.forEach(col => {
            doc.text(col.header, xPosition, yPosition + 5);
            xPosition += contentWidth * col.width;
        });
        
        yPosition += rowHeight;
        
        // Données
        doc.setFont(undefined, 'normal');
        services.forEach(service => {
            if (yPosition > doc.internal.pageSize.getHeight() - 20) {
                doc.addPage();
                yPosition = margin;
            }
            
            xPosition = margin + 2;
            const status = service.is_open ? 'Ouvert' : 'Fermé';
            const capacityColor = service.capacity_percentage > 80 ? '#dc3545' : 
                                service.capacity_percentage > 60 ? '#ffc107' : '#28a745';
            
            doc.text(service.name, xPosition, yPosition + 5);
            xPosition += contentWidth * cols[0].width;
            
            doc.text(status, xPosition, yPosition + 5);
            xPosition += contentWidth * cols[1].width;
            
            doc.text(service.waiting_count.toString(), xPosition, yPosition + 5);
            xPosition += contentWidth * cols[2].width;
            
            doc.setTextColor(capacityColor);
            doc.text(`${service.capacity_percentage}%`, xPosition, yPosition + 5);
            doc.setTextColor(0, 0, 0); // Reset color
            
            yPosition += rowHeight;
        });
        
        return yPosition + 3;
    }

    /**
     * Ajoute un tableau de tickets
     */
    addTicketsTable(doc, tickets, yPosition, margin, contentWidth, type = 'waiting') {
        const rowHeight = 7;
        const cols = type === 'waiting' ? [
            { header: 'Ticket', width: 0.2 },
            { header: 'Service', width: 0.3 },
            { header: 'Client', width: 0.3 },
            { header: 'Attente', width: 0.2 }
        ] : [
            { header: 'Ticket', width: 0.2 },
            { header: 'Service', width: 0.3 },
            { header: 'Client', width: 0.3 },
            { header: 'Agent', width: 0.2 }
        ];
        
        // En-tête
        doc.setFillColor(240, 240, 240);
        doc.rect(margin, yPosition, contentWidth, rowHeight, 'F');
        doc.setFontSize(9);
        doc.setFont(undefined, 'bold');
        
        let xPosition = margin + 2;
        cols.forEach(col => {
            doc.text(col.header, xPosition, yPosition + 5);
            xPosition += contentWidth * col.width;
        });
        
        yPosition += rowHeight;
        
        // Données (limitées pour éviter les PDF trop longs)
        const displayTickets = tickets.slice(0, 20);
        doc.setFont(undefined, 'normal');
        
        displayTickets.forEach(ticket => {
            if (yPosition > doc.internal.pageSize.getHeight() - 20) {
                doc.addPage();
                yPosition = margin;
            }
            
            xPosition = margin + 2;
            doc.text(ticket.number.toString(), xPosition, yPosition + 5);
            xPosition += contentWidth * cols[0].width;
            
            doc.text(ticket.service_name, xPosition, yPosition + 5);
            xPosition += contentWidth * cols[1].width;
            
            doc.text(ticket.customer_name, xPosition, yPosition + 5);
            xPosition += contentWidth * cols[2].width;
            
            if (type === 'waiting') {
                doc.text(`${ticket.estimated_wait} min`, xPosition, yPosition + 5);
            } else {
                doc.text(ticket.agent_name, xPosition, yPosition + 5);
            }
            
            yPosition += rowHeight;
        });
        
        // Message si tickets tronqués
        if (tickets.length > 20) {
            doc.setFontSize(8);
            doc.setTextColor(128, 128, 128);
            doc.text(`... et ${tickets.length - 20} tickets supplémentaires`, margin, yPosition + 5);
            doc.setTextColor(0, 0, 0);
            yPosition += 8;
        }
        
        return yPosition + 3;
    }

    /**
     * Ajoute un message "Aucune donnée"
     */
    addNoDataMessage(doc, yPosition) {
        doc.setFontSize(10);
        doc.setTextColor(128, 128, 128);
        doc.text('Aucune donnée disponible', margin, yPosition + 5);
        doc.setTextColor(0, 0, 0);
        return yPosition + 10;
    }

    /**
     * Ajoute le pied de page
     */
    addFooter(doc, pageWidth) {
        const footerY = doc.internal.pageSize.getHeight() - 10;
        doc.setFontSize(8);
        doc.setTextColor(128, 128, 128);
        doc.text('Généré par Queue Management System', pageWidth / 2, footerY, { align: 'center' });
    }

    

















    /**
     * Génère les données du rapport
     */
    async generateReportData() {
        const currentData = this.prepareExportData();

        // Calculer des métriques supplémentaires pour le rapport
        const reportMetrics = {
            efficiency_metrics: {
                avg_service_time: this.calculateAverageServiceTime(),
                peak_hours: this.identifyPeakHours(),
                bottleneck_services: this.identifyBottlenecks(),
                customer_satisfaction_score: this.calculateSatisfactionScore()
            },
            trend_analysis: {
                daily_trend: this.analyzeDailyTrend(),
                service_usage_patterns: this.analyzeServiceUsagePatterns(),
                waiting_time_trends: this.analyzeWaitingTimeTrends()
            },
            recommendations: this.generateRecommendations()
        };

        return {
            ...currentData,
            ...reportMetrics,
            report_generated_at: new Date().toISOString()
        };
    }

    /**
     * Calcule le temps de service moyen
     */
    calculateAverageServiceTime() {
        if (!this.dashboardData.serving_tickets.length) return 0;

        const totalDuration = this.dashboardData.serving_tickets.reduce(
            (sum, ticket) => sum + (ticket.service_duration || 0), 0
        );
        return totalDuration / this.dashboardData.serving_tickets.length;
    }

    /**
     * Identifie les heures de pointe
     */
    identifyPeakHours() {
        // Cette méthode analyserait les données historiques pour identifier les patterns
        // Pour l'instant, retournons des données d'exemple
        return {
            morning_peak: "09:00-11:00",
            afternoon_peak: "14:00-16:00",
            highest_load_hour: "10:00"
        };
    }

    /**
     * Identifie les services en goulot d'étranglement
     */
    identifyBottlenecks() {
        return this.dashboardData.services
            .filter(service => service.capacity_percentage > 80)
            .map(service => ({
                name: service.name,
                capacity_percentage: service.capacity_percentage,
                waiting_count: service.waiting_count,
                severity: service.capacity_percentage > 95 ? 'critical' : 'high'
            }));
    }

    /**
     * Calcule un score de satisfaction approximatif
     */
    calculateSatisfactionScore() {
        const avgWaitTime = this.stats.average_wait_time || 0;
        const completionRate = this.stats.completion_rate || 0;

        // Score basé sur le temps d'attente et le taux de completion
        let score = 100;
        score -= Math.min(avgWaitTime * 2, 40); // Pénalité pour temps d'attente élevé
        score = (score * completionRate / 100); // Ajusté par le taux de completion

        return Math.max(0, Math.min(100, score));
    }

    /**
     * Analyse les tendances quotidiennes
     */
    analyzeDailyTrend() {
        if (!this.dashboardData.historical_data.length) {
            return { trend: 'stable', change_percentage: 0 };
        }

        const data = this.dashboardData.historical_data;
        const recent = data.slice(-5); // 5 derniers points

        if (recent.length < 2) {
            return { trend: 'insufficient_data', change_percentage: 0 };
        }

        const first = recent[0].total_tickets;
        const last = recent[recent.length - 1].total_tickets;
        const change = ((last - first) / first) * 100;

        return {
            trend: change > 5 ? 'increasing' : change < -5 ? 'decreasing' : 'stable',
            change_percentage: Math.round(change * 100) / 100
        };
    }

    /**
     * Analyse les patterns d'usage des services
     */
    analyzeServiceUsagePatterns() {
        return this.dashboardData.services.map(service => ({
            name: service.name,
            usage_level: this.getUsageLevel(service.total_tickets_today),
            efficiency: this.calculateServiceEfficiency(service)
        }));
    }

    /**
     * Analyse les tendances des temps d'attente
     */
    analyzeWaitingTimeTrends() {
        const avgWaitTime = this.stats.average_wait_time || 0;
        return {
            current_avg: avgWaitTime,
            status: avgWaitTime < 5 ? 'excellent' : avgWaitTime < 10 ? 'good' : 'needs_improvement',
            target_improvement: Math.max(0, avgWaitTime - 5)
        };
    }

    /**
     * Génère des recommandations basées sur les données
     */
    generateRecommendations() {
        const recommendations = [];

        // Recommandations basées sur les goulots d'étranglement
        const bottlenecks = this.identifyBottlenecks();
        if (bottlenecks.length > 0) {
            recommendations.push({
                type: 'capacity',
                priority: 'high',
                message: `${bottlenecks.length} service(s) en surcharge détecté(s). Considérez augmenter la capacité.`,
                affected_services: bottlenecks.map(b => b.name)
            });
        }

        // Recommandations basées sur le temps d'attente
        const avgWaitTime = this.stats.average_wait_time || 0;
        if (avgWaitTime > 10) {
            recommendations.push({
                type: 'efficiency',
                priority: 'medium',
                message: 'Le temps d\'attente moyen est élevé. Optimisez les processus de service.',
                current_avg: avgWaitTime,
                target_avg: 5
            });
        }

        // Recommandations basées sur les tickets annulés
        const cancelledRate = (this.stats.cancelled_tickets + this.stats.no_show_tickets) /
            Math.max(this.stats.total_tickets, 1) * 100;
        if (cancelledRate > 10) {
            recommendations.push({
                type: 'retention',
                priority: 'medium',
                message: 'Taux d\'abandon élevé. Améliorez la communication et réduisez les temps d\'attente.',
                cancelled_rate: Math.round(cancelledRate * 100) / 100
            });
        }

        return recommendations;
    }

    // ========== MÉTHODES UTILITAIRES POUR L'EXPORT ==========

    /**
     * Formate les en-têtes CSV
     */
    formatCSVHeader(header) {
        return header.replace(/_/g, ' ')
            .split(' ')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }

    /**
     * Échappe les valeurs CSV
     */
    escapeCSV(value) {
        if (value === null || value === undefined) return '';
        const str = String(value);
        if (str.includes(',') || str.includes('"') || str.includes('\n')) {
            return `"${str.replace(/"/g, '""')}"`;
        }
        return str;
    }

    /**
     * Détermine le niveau d'usage d'un service
     */
    getUsageLevel(totalTickets) {
        if (totalTickets > 50) return 'high';
        if (totalTickets > 20) return 'medium';
        return 'low';
    }

    /**
     * Calcule l'efficacité d'un service
     */
    calculateServiceEfficiency(service) {
        const total = service.waiting_count + service.serving_count + service.served_count;
        if (total === 0) return 0;
        return Math.round((service.served_count / total) * 100);
    }

    /**
     * Calcule le nombre total d'enregistrements
     */
    calculateTotalRecords() {
        return this.dashboardData.services.length +
            this.dashboardData.waiting_tickets.length +
            this.dashboardData.serving_tickets.length;
    }

    /**
     * Télécharge un fichier texte
     */
    downloadFile(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        this.downloadBlob(blob, filename);
    }

    /**
     * Télécharge un blob
     */
    downloadBlob(blob, filename) {
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);
    }

    /**
     * Charge Chart.js de manière asynchrone et initialise les graphiques
     */
    async loadChartLibraryAndInit() {
        if (!this.state.chartsEnabled || this.state.chartsCreationInProgress) return;

        try {
            console.log("Loading Chart.js library...");
            this.state.chartsCreationInProgress = true;

            // Vérifier si Chart.js est déjà chargé globalement
            if (window.Chart) {
                this.Chart = window.Chart;
                this.state.chartLibraryLoaded = true;
                console.log("Chart.js already available globally");
            } else {
                // Charger Chart.js dynamiquement
                await this.loadChartJSLibrary();
            }

            if (this.Chart && !this.state.chartsInitialized) {
                // Attendre un court délai pour s'assurer que le DOM est prêt
                setTimeout(() => {
                    this.initAllCharts();
                    this.state.chartsInitialized = true;
                    console.log("Charts initialized successfully");
                }, 200);
            }
        } catch (error) {
            console.error("Failed to load Chart.js:", error);
            this.state.chartsEnabled = false;
            this.state.chartLibraryLoaded = false;
            this.notification.add("Impossible de charger les graphiques", {
                type: "warning"
            });
        } finally {
            this.state.chartsCreationInProgress = false;
        }
    }

    /**
     * Charge Chart.js depuis le CDN
     */
    async loadChartJSLibrary() {
        return new Promise((resolve, reject) => {
            // Vérifier si le script est déjà chargé
            if (document.querySelector('script[src*="chart.min.js"]')) {
                if (window.Chart) {
                    this.Chart = window.Chart;
                    this.state.chartLibraryLoaded = true;
                    resolve();
                    return;
                }
            }

            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js';
            script.async = true;

            script.onload = () => {
                if (window.Chart) {
                    this.Chart = window.Chart;
                    this.state.chartLibraryLoaded = true;
                    console.log("Chart.js loaded successfully from CDN");
                    resolve();
                } else {
                    reject(new Error("Chart.js loaded but Chart constructor not available"));
                }
            };

            script.onerror = () => {
                reject(new Error("Failed to load Chart.js from CDN"));
            };

            document.head.appendChild(script);

            // Timeout de sécurité
            setTimeout(() => {
                if (!this.state.chartLibraryLoaded) {
                    reject(new Error("Chart.js loading timeout"));
                }
            }, 10000);
        });
    }

    async initializeDashboard() {
        try {
            await this.fetchDataWithRetry();
        } catch (error) {
            console.error("Failed to initialize dashboard:", error);
            this.handleInitializationError(error);
        }
    }

    setupEventListeners() {
        document.addEventListener('visibilitychange', this.handleVisibilityChange);
        window.addEventListener('online', this.handleOnlineStatus);
        window.addEventListener('offline', this.handleOnlineStatus);
    }

    handleVisibilityChange() {
        if (document.hidden) {
            this.clearAutoRefresh();
        } else if (this.state.autoRefresh) {
            this.setupAutoRefresh();
            this.reloadDashboard();
        }
    }

    handleOnlineStatus() {
        if (navigator.onLine && this.state.connectionError) {
            this.state.connectionError = false;
            this.state.retryAttempts = 0;
            this.reloadDashboard();
        } else if (!navigator.onLine) {
            this.state.connectionError = true;
            this.clearAutoRefresh();
        }
    }

    handleWindowResize() {
        if (this.state.chartsEnabled && this.state.chartsInitialized) {
            // Debounce le redimensionnement
            clearTimeout(this._resizeTimeout);
            this._resizeTimeout = setTimeout(() => {
                this.resizeAllCharts();
            }, 250);
        }
    }

    cleanup() {
        this.clearAutoRefresh();
        this.clearRetryTimeout();
        document.removeEventListener('visibilitychange', this.handleVisibilityChange);
        window.removeEventListener('online', this.handleOnlineStatus);
        window.removeEventListener('offline', this.handleOnlineStatus);

        // Nettoyer le timeout de redimensionnement
        if (this._resizeTimeout) {
            clearTimeout(this._resizeTimeout);
        }
    }

    clearRetryTimeout() {
        if (this.retryTimeout) {
            clearTimeout(this.retryTimeout);
            this.retryTimeout = null;
        }
    }

    // ========== MÉTHODES POUR LES GRAPHIQUES ==========

    /**
     * Initialise tous les graphiques avec gestion d'erreur améliorée
     * MODIFIÉ : Ne plus détruire les graphiques existants systématiquement
     */
    initAllCharts() {
        if (!this.state.chartsEnabled || !this.Chart || this.state.chartsCreationInProgress) {
            console.warn("Charts disabled, Chart.js not loaded, or creation in progress");
            return;
        }

        try {
            console.log("Initializing all charts...");

            // Vérifier que les refs sont disponibles
            const refs = [this.servicesChartRef, this.statsChartRef, this.waitingTimeChartRef, this.performanceChartRef];
            const availableRefs = refs.filter(ref => ref && ref.el);

            if (availableRefs.length === 0) {
                console.warn("No chart canvas elements found, retrying in 500ms");
                setTimeout(() => this.initAllCharts(), 500);
                return;
            }

            // Créer seulement les graphiques qui n'existent pas encore
            if (!this.charts.services) this.createServicesChart();
            if (!this.charts.stats) this.createStatsChart();
            if (!this.charts.waitingTime) this.createWaitingTimeChart();
            if (!this.charts.performance) this.createPerformanceChart();

            this.state.chartsInitialized = true;
            console.log("All charts initialized successfully");

        } catch (error) {
            console.error("Error initializing charts:", error);
            // Ne pas désactiver complètement les graphiques, juste marquer comme non initialisés
            this.state.chartsInitialized = false;
        }
    }

    /**
     * Met à jour tous les graphiques
     * MODIFIÉ : Meilleure gestion des erreurs sans réinitialisation complète
     */
    updateAllCharts() {
        if (!this.state.chartsEnabled || !this.Chart) {
            return;
        }

        // Si les graphiques ne sont pas initialisés, les initialiser d'abord
        if (!this.state.chartsInitialized) {
            console.log("Charts not initialized, initializing now...");
            this.initAllCharts();
            return;
        }

        try {
            this.updateServicesChart();
            this.updateStatsChart();
            this.updateWaitingTimeChart();
            this.updatePerformanceChart();
        } catch (error) {
            console.error("Error updating charts:", error);
            // Essayer de récréer seulement le graphique en erreur
            this.handleChartUpdateError(error);
        }
    }

    /**
     * NOUVEAU : Gère les erreurs de mise à jour des graphiques
     */
    handleChartUpdateError(error) {
        console.warn("Chart update failed, attempting to recreate charts...");

        // Vérifier quels graphiques sont encore valides
        Object.keys(this.charts).forEach(key => {
            if (this.charts[key] && this.charts[key].canvas && !this.charts[key].canvas.parentNode) {
                // Le canvas a été supprimé du DOM, détruire la référence
                console.warn(`Chart ${key} canvas removed from DOM, destroying reference`);
                this.charts[key] = null;
            }
        });

        // Réinitialiser seulement si nécessaire
        setTimeout(() => {
            if (this.state.chartsEnabled) {
                this.initAllCharts();
            }
        }, 1000);
    }

    /**
     * Détruit tous les graphiques
     */
    destroyAllCharts() {
        Object.keys(this.charts).forEach(key => {
            if (this.charts[key]) {
                try {
                    this.charts[key].destroy();
                } catch (error) {
                    console.warn(`Error destroying ${key} chart:`, error);
                }
                this.charts[key] = null;
            }
        });
        this.state.chartsInitialized = false;
    }

    /**
     * Redimensionne tous les graphiques
     */
    resizeAllCharts() {
        Object.values(this.charts).forEach(chart => {
            if (chart && typeof chart.resize === 'function') {
                try {
                    chart.resize();
                } catch (error) {
                    console.warn("Error resizing chart:", error);
                }
            }
        });
    }

    // ========== CRÉATION DES GRAPHIQUES INDIVIDUELS ==========

    createServicesChart() {
        if (!this.servicesChartRef || !this.servicesChartRef.el || !this.Chart || this.charts.services) return;

        try {
            const ctx = this.servicesChartRef.el.getContext('2d');
            const config = this.getServicesChartConfig();
            this.charts.services = new this.Chart(ctx, config);
            console.log("Services chart created successfully");
        } catch (error) {
            console.error("Error creating services chart:", error);
        }
    }

    createStatsChart() {
        if (!this.statsChartRef || !this.statsChartRef.el || !this.Chart || this.charts.stats) return;

        try {
            const ctx = this.statsChartRef.el.getContext('2d');
            const config = this.getStatsChartConfig();
            this.charts.stats = new this.Chart(ctx, config);
            console.log("Stats chart created successfully");
        } catch (error) {
            console.error("Error creating stats chart:", error);
        }
    }

    createWaitingTimeChart() {
        if (!this.waitingTimeChartRef || !this.waitingTimeChartRef.el || !this.Chart || this.charts.waitingTime) return;

        try {
            const ctx = this.waitingTimeChartRef.el.getContext('2d');
            const config = this.getWaitingTimeChartConfig();
            this.charts.waitingTime = new this.Chart(ctx, config);
            console.log("Waiting time chart created successfully");
        } catch (error) {
            console.error("Error creating waiting time chart:", error);
        }
    }

    createPerformanceChart() {
        if (!this.performanceChartRef || !this.performanceChartRef.el || !this.Chart || this.charts.performance) return;

        try {
            const ctx = this.performanceChartRef.el.getContext('2d');
            const config = this.getPerformanceChartConfig();
            this.charts.performance = new this.Chart(ctx, config);
            console.log("Performance chart created successfully");
        } catch (error) {
            console.error("Error creating performance chart:", error);
        }
    }

    // ========== MISE À JOUR DES GRAPHIQUES INDIVIDUELS ==========
    // MODIFIÉ : Vérifications supplémentaires avant mise à jour

    updateServicesChart() {
        if (!this.charts.services || !this.isChartValid(this.charts.services)) {
            console.log("Services chart not valid, recreating...");
            this.charts.services = null;
            this.createServicesChart();
            return;
        }
        try {
            const config = this.getServicesChartConfig();
            this.charts.services.data = config.data;
            this.charts.services.update('none');
        } catch (error) {
            console.error("Error updating services chart:", error);
            this.charts.services = null;
        }
    }

    updateStatsChart() {
        if (!this.charts.stats || !this.isChartValid(this.charts.stats)) {
            console.log("Stats chart not valid, recreating...");
            this.charts.stats = null;
            this.createStatsChart();
            return;
        }
        try {
            const config = this.getStatsChartConfig();
            this.charts.stats.data = config.data;
            this.charts.stats.update('none');
        } catch (error) {
            console.error("Error updating stats chart:", error);
            this.charts.stats = null;
        }
    }

    updateWaitingTimeChart() {
        if (!this.charts.waitingTime || !this.isChartValid(this.charts.waitingTime)) {
            console.log("Waiting time chart not valid, recreating...");
            this.charts.waitingTime = null;
            this.createWaitingTimeChart();
            return;
        }
        try {
            const config = this.getWaitingTimeChartConfig();
            this.charts.waitingTime.data = config.data;
            this.charts.waitingTime.update('none');
        } catch (error) {
            console.error("Error updating waiting time chart:", error);
            this.charts.waitingTime = null;
        }
    }

    updatePerformanceChart() {
        if (!this.charts.performance || !this.isChartValid(this.charts.performance)) {
            console.log("Performance chart not valid, recreating...");
            this.charts.performance = null;
            this.createPerformanceChart();
            return;
        }
        try {
            const config = this.getPerformanceChartConfig();
            this.charts.performance.data = config.data;
            this.charts.performance.update('none');
        } catch (error) {
            console.error("Error updating performance chart:", error);
            this.charts.performance = null;
        }
    }

    /**
     * NOUVEAU : Vérifie si un graphique est encore valide
     */
    isChartValid(chart) {
        return chart &&
            chart.canvas &&
            document.body.contains(chart.canvas) &&
            typeof chart.update === 'function' &&
            !chart.destroyed;
    }


    // ========== CONFIGURATIONS DES GRAPHIQUES ==========
    // [Les méthodes de configuration restent identiques]

    getServicesChartConfig() {
        const services = this.state.dashboardData.services;
        return {
            type: 'bar',
            data: {
                labels: services.map(s => s.name),
                datasets: [{
                    label: 'En attente',
                    data: services.map(s => s.waiting_count),
                    backgroundColor: 'rgba(255, 193, 7, 0.8)',
                    borderColor: 'rgba(255, 193, 7, 1)',
                    borderWidth: 1
                }, {
                    label: 'En service',
                    data: services.map(s => s.serving_count),
                    backgroundColor: 'rgba(0, 123, 255, 0.8)',
                    borderColor: 'rgba(0, 123, 255, 1)',
                    borderWidth: 1
                }, {
                    label: 'Terminés',
                    data: services.map(s => s.served_count),
                    backgroundColor: 'rgba(40, 167, 69, 0.8)',
                    borderColor: 'rgba(40, 167, 69, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'État des Files par Service'
                    },
                    legend: {
                        position: 'top'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1
                        }
                    }
                }
            }
        };
    }

    getStatsChartConfig() {
        const stats = this.state.dashboardData.stats;
        return {
            type: 'doughnut',
            data: {
                labels: ['Terminés', 'En Attente', 'En Service', 'Annulés/Absents'],
                datasets: [{
                    data: [
                        stats.completed_tickets || 0,
                        stats.waiting_tickets || 0,
                        stats.serving_tickets || 0,
                        (stats.cancelled_tickets || 0) + (stats.no_show_tickets || 0)
                    ],
                    backgroundColor: [
                        'rgba(40, 167, 69, 0.8)',
                        'rgba(255, 193, 7, 0.8)',
                        'rgba(0, 123, 255, 0.8)',
                        'rgba(108, 117, 125, 0.8)'
                    ],
                    borderColor: [
                        'rgba(40, 167, 69, 1)',
                        'rgba(255, 193, 7, 1)',
                        'rgba(0, 123, 255, 1)',
                        'rgba(108, 117, 125, 1)'
                    ],
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Répartition des Tickets'
                    },
                    legend: {
                        position: 'right'
                    }
                }
            }
        };
    }

    getWaitingTimeChartConfig() {
        const services = this.state.dashboardData.services;
        return {
            type: 'line',
            data: {
                labels: services.map(s => s.name),
                datasets: [{
                    label: 'Temps d\'attente moyen (min)',
                    data: services.map(s => s.avg_waiting_time || 0),
                    backgroundColor: 'rgba(255, 99, 132, 0.8)',
                    borderColor: 'rgba(255, 99, 132, 1)',
                    borderWidth: 2,
                    fill: false,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Temps d\'Attente par Service'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Minutes'
                        }
                    }
                }
            }
        };
    }

    getPerformanceChartConfig() {
        const services = this.state.dashboardData.services;
        return {
            type: 'bar',
            data: {
                labels: services.map(s => s.name),
                datasets: [{
                    label: 'Utilisation de capacité (%)',
                    data: services.map(s => s.capacity_percentage || 0),
                    backgroundColor: services.map(s => {
                        const pct = s.capacity_percentage || 0;
                        if (pct > 80) return 'rgba(220, 53, 69, 0.8)';
                        if (pct > 60) return 'rgba(255, 193, 7, 0.8)';
                        return 'rgba(40, 167, 69, 0.8)';
                    }),
                    borderColor: services.map(s => {
                        const pct = s.capacity_percentage || 0;
                        if (pct > 80) return 'rgba(220, 53, 69, 1)';
                        if (pct > 60) return 'rgba(255, 193, 7, 1)';
                        return 'rgba(40, 167, 69, 1)';
                    }),
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Performance des Services'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        title: {
                            display: true,
                            text: 'Pourcentage'
                        }
                    }
                }
            }
        };
    }

    // ========== GESTION DES DONNÉES ==========
    // MODIFIÉ : Amélioration de la mise à jour des graphiques

    async fetchDataWithRetry() {
        for (let attempt = 0; attempt <= this.MAX_RETRY_ATTEMPTS; attempt++) {
            try {
                await this.fetchData();
                this.state.retryAttempts = 0;
                this.state.connectionError = false;
                return;
            } catch (error) {
                this.state.retryAttempts = attempt + 1;

                if (attempt === this.MAX_RETRY_ATTEMPTS) {
                    this.state.connectionError = true;
                    throw error;
                }

                const delay = this.RETRY_DELAY_BASE * Math.pow(2, attempt);
                console.warn(`Fetch attempt ${attempt + 1} failed, retrying in ${delay}ms:`, error);

                await new Promise(resolve => {
                    this.retryTimeout = setTimeout(resolve, delay);
                });
            }
        }
    }

    async fetchData() {
        if (!navigator.onLine) {
            throw new Error("No internet connection");
        }

        try {
            this.state.isLoading = true;

            const timeoutPromise = new Promise((_, reject) =>
                setTimeout(() => reject(new Error("Request timeout")), this.REQUEST_TIMEOUT)
            );

            const dataPromise = this.orm.call("queue.service", "get_dashboard_data", []);
            const result = await Promise.race([dataPromise, timeoutPromise]);

            this.validateAndSetData(result);

            // Mettre à jour les graphiques après avoir reçu les données
            // MODIFIÉ : Délai réduit et vérification supplémentaire
            if (this.state.chartsEnabled) {
                setTimeout(() => {
                    if (this.state.chartsInitialized) {
                        this.updateAllCharts();
                    } else {
                        this.initAllCharts();
                    }
                }, 50);
            }

        } catch (error) {
            console.error("Dashboard fetch error:", error);
            this.handleFetchError(error);
            throw error;
        } finally {
            this.state.isLoading = false;
        }
    }

    // [Toutes les méthodes de validation et autres restent identiques...]
    validateAndSetData(result) {
        if (!result || typeof result !== 'object') {
            throw new Error("Invalid response format");
        }

        try {
            this.state.dashboardData = {
                services: this.validateServices(result.services),
                waiting_tickets: this.validateTickets(result.waiting_tickets),
                serving_tickets: this.validateTickets(result.serving_tickets),
                stats: this.validateStats(result.stats),
                historical_data: this.validateHistoricalData(result.historical_data)
            };

            this.state.lastUpdate = this.validateTimestamp(result.last_update) || new Date().toLocaleTimeString();

        } catch (validationError) {
            console.error("Data validation error:", validationError);
            throw new Error(`Data validation failed: ${validationError.message}`);
        }
    }

    // [Toutes les autres méthodes de validation restent identiques...]
    validateServices(services) {
        if (!Array.isArray(services)) {
            console.warn("Services data is not an array, using empty array");
            return [];
        }

        return services.map((service, index) => {
            try {
                if (!service || typeof service !== 'object') {
                    throw new Error(`Invalid service object at index ${index}`);
                }

                return {
                    id: this.validatePositiveInteger(service.id, `Service ID at index ${index}`),
                    name: this.validateString(service.name, 'Service Inconnu'),
                    is_open: Boolean(service.is_open),
                    waiting_count: this.validateNonNegativeInteger(service.waiting_count, 0),
                    serving_count: this.validateNonNegativeInteger(service.serving_count, 0),
                    served_count: this.validateNonNegativeInteger(service.served_count, 0),
                    total_tickets_today: this.validateNonNegativeInteger(service.total_tickets_today, 0),
                    current_ticket: this.validateNonNegativeInteger(service.current_ticket, 0),
                    avg_waiting_time: this.validateNonNegativeNumber(service.avg_waiting_time, 0),
                    capacity_percentage: this.validatePercentage(service.capacity_percentage, 0)
                };
            } catch (error) {
                console.error(`Service validation error:`, error);
                return this.getDefaultService(service?.id || index);
            }
        }).filter(Boolean);
    }

    validateTickets(tickets) {
        if (!Array.isArray(tickets)) {
            console.warn("Tickets data is not an array, using empty array");
            return [];
        }

        return tickets.map((ticket, index) => {
            try {
                if (!ticket || typeof ticket !== 'object') {
                    throw new Error(`Invalid ticket object at index ${index}`);
                }

                return {
                    id: this.validatePositiveInteger(ticket.id, `Ticket ID at index ${index}`),
                    number: this.validateNonNegativeInteger(ticket.number, 0),
                    service_id: this.validatePositiveInteger(ticket.service_id, `Service ID for ticket at index ${index}`),
                    service_name: this.validateString(ticket.service_name, 'Service Inconnu'),
                    customer_name: this.validateString(ticket.customer_name, 'Client Anonyme'),
                    created_time: this.validateString(ticket.created_time, ''),
                    served_time: this.validateString(ticket.served_time, ''),
                    service_duration: this.validateNonNegativeNumber(ticket.service_duration, 0),
                    estimated_wait: this.validateNonNegativeNumber(ticket.estimated_wait, 0),
                    priority: this.validatePriority(ticket.priority),
                    position_in_queue: this.validatePositiveInteger(ticket.position_in_queue, 1, 1),
                    agent_name: this.validateString(ticket.agent_name, 'Agent')
                };
            } catch (error) {
                console.error(`Ticket validation error:`, error);
                return this.getDefaultTicket(ticket?.id || index);
            }
        }).filter(Boolean);
    }

    validateStats(stats) {
        if (!stats || typeof stats !== 'object') {
            console.warn("Stats data is invalid, using default stats");
            return this.getDefaultStats();
        }

        try {
            return {
                total_tickets: this.validateNonNegativeInteger(stats.total_tickets, 0),
                completed_tickets: this.validateNonNegativeInteger(stats.completed_tickets, 0),
                waiting_tickets: this.validateNonNegativeInteger(stats.waiting_tickets, 0),
                serving_tickets: this.validateNonNegativeInteger(stats.serving_tickets, 0),
                cancelled_tickets: this.validateNonNegativeInteger(stats.cancelled_tickets, 0),
                no_show_tickets: this.validateNonNegativeInteger(stats.no_show_tickets, 0),
                average_wait_time: this.validateNonNegativeNumber(stats.average_wait_time, 0),
                completion_rate: this.validatePercentage(stats.completion_rate, 0),
                active_services: this.validateNonNegativeInteger(stats.active_services, 0),
                total_services: this.validateNonNegativeInteger(stats.total_services, 0)
            };
        } catch (error) {
            console.error("Stats validation error:", error);
            return this.getDefaultStats();
        }
    }

    validateHistoricalData(historical_data) {
        if (!Array.isArray(historical_data)) {
            return [];
        }
        return historical_data.map(point => ({
            time: point.time || new Date().toISOString(),
            total_tickets: parseInt(point.total_tickets) || 0,
            waiting_tickets: parseInt(point.waiting_tickets) || 0,
            serving_tickets: parseInt(point.serving_tickets) || 0,
            completed_tickets: parseInt(point.completed_tickets) || 0,
            avg_wait_time: parseFloat(point.avg_wait_time) || 0
        }));
    }

    // Méthodes utilitaires de validation
    validatePositiveInteger(value, fieldName, defaultValue = 0) {
        const num = parseInt(value);
        if (isNaN(num) || num <= 0) {
            if (fieldName) console.warn(`Invalid ${fieldName}: ${value}, using default: ${defaultValue}`);
            return Math.max(1, defaultValue);
        }
        return num;
    }

    validateNonNegativeInteger(value, defaultValue = 0) {
        const num = parseInt(value);
        if (isNaN(num) || num < 0) {
            return Math.max(0, defaultValue);
        }
        return num;
    }

    validateNonNegativeNumber(value, defaultValue = 0) {
        const num = parseFloat(value);
        if (isNaN(num) || num < 0) {
            return Math.max(0, defaultValue);
        }
        return num;
    }

    validatePercentage(value, defaultValue = 0) {
        const num = parseFloat(value);
        if (isNaN(num)) {
            return Math.max(0, Math.min(100, defaultValue));
        }
        return Math.max(0, Math.min(100, num));
    }

    validateString(value, defaultValue = '') {
        if (typeof value !== 'string') {
            return defaultValue;
        }
        return value.trim() || defaultValue;
    }

    validatePriority(priority) {
        const validPriorities = ['normal', 'high', 'urgent'];
        return validPriorities.includes(priority) ? priority : 'normal';
    }

    validateTimestamp(timestamp) {
        if (!timestamp) return null;

        try {
            const date = new Date(timestamp);
            if (isNaN(date.getTime())) {
                return null;
            }
            return date.toLocaleTimeString();
        } catch {
            return null;
        }
    }

    // Objets par défaut
    getDefaultService(id = 0) {
        return {
            id: id,
            name: 'Service Inconnu',
            is_open: false,
            waiting_count: 0,
            serving_count: 0,
            served_count: 0,
            total_tickets_today: 0,
            current_ticket: 0,
            avg_waiting_time: 0,
            capacity_percentage: 0
        };
    }

    getDefaultTicket(id = 0) {
        return {
            id: id,
            number: 0,
            service_id: 0,
            service_name: 'Service Inconnu',
            customer_name: 'Client Anonyme',
            created_time: '',
            served_time: '',
            service_duration: 0,
            estimated_wait: 0,
            priority: 'normal',
            position_in_queue: 1,
            agent_name: 'Agent'
        };
    }

    getDefaultStats() {
        return {
            total_tickets: 0,
            completed_tickets: 0,
            waiting_tickets: 0,
            serving_tickets: 0,
            cancelled_tickets: 0,
            no_show_tickets: 0,
            average_wait_time: 0,
            completion_rate: 0,
            active_services: 0,
            total_services: 0
        };
    }

    // ========== GESTION DES ERREURS ==========

    handleFetchError(error) {
        const errorMessage = this.getErrorMessage(error);

        this.notification.add(`Erreur de connexion: ${errorMessage}`, {
            type: "danger",
            sticky: this.state.retryAttempts >= this.MAX_RETRY_ATTEMPTS
        });

        if (this.state.retryAttempts >= this.MAX_RETRY_ATTEMPTS) {
            this.resetToDefaultData();
        }
    }

    handleInitializationError(error) {
        console.error("Dashboard initialization failed:", error);
        this.resetToDefaultData();

        this.notification.add("Impossible de charger le dashboard. Données par défaut utilisées.", {
            type: "warning",
            sticky: true
        });
    }

    getErrorMessage(error) {
        if (!navigator.onLine) {
            return "Pas de connexion internet";
        }

        if (error.message === "Request timeout") {
            return "Délai d'attente dépassé";
        }

        if (error.message && error.message.includes("validation")) {
            return "Données invalides reçues du serveur";
        }

        return error.message || "Erreur inconnue";
    }

    resetToDefaultData() {
        this.state.dashboardData = {
            services: [],
            waiting_tickets: [],
            serving_tickets: [],
            stats: this.getDefaultStats(),
            historical_data: []
        };
    }

    // ========== OPÉRATIONS DASHBOARD ==========

    async executeOperation(operation, operationName, ticketId = null, serviceId = null) {
        const operationKey = `${operationName}_${ticketId || serviceId || Date.now()}`;

        if (this.state.operationInProgress.has(operationKey)) {
            console.warn(`Operation ${operationName} already in progress`);
            return;
        }

        try {
            this.state.operationInProgress.add(operationKey);
            const result = await operation();
            await this.reloadDashboard();
            return result;
        } catch (error) {
            console.error(`${operationName} error:`, error);
            throw error;
        } finally {
            this.state.operationInProgress.delete(operationKey);
        }
    }

    async callNextTicket(ticketId) {
        try {
            await this.executeOperation(
                () => this.orm.call("queue.ticket", "action_call_next", [[ticketId]]),
                "call_next_ticket",
                ticketId
            );

            this.notification.add("Ticket appelé avec succès", {
                type: "success",
            });
        } catch (error) {
            this.notification.add(`Erreur lors de l'appel du ticket: ${this.getErrorMessage(error)}`, {
                type: "danger",
            });
        }
    }

    async completeService(ticketId) {
        try {
            await this.executeOperation(
                () => this.orm.call("queue.ticket", "action_complete_service", [[ticketId]]),
                "complete_service",
                ticketId
            );

            this.notification.add("Service terminé avec succès", {
                type: "success",
            });
        } catch (error) {
            this.notification.add(`Erreur lors de la completion du service: ${this.getErrorMessage(error)}`, {
                type: "danger",
            });
        }
    }

    async generateTicket(serviceId) {
        try {
            const result = await this.executeOperation(
                () => this.orm.call("queue.service", "action_generate_quick_ticket", [[serviceId]]),
                "generate_ticket",
                null,
                serviceId
            );

            if (result && result.params && result.params.message) {
                this.notification.add(result.params.message, {
                    type: "success",
                    sticky: true
                });
            } else {
                this.notification.add("Ticket généré avec succès", {
                    type: "success",
                });
            }
        } catch (error) {
            this.notification.add(`Erreur lors de la génération du ticket: ${this.getErrorMessage(error)}`, {
                type: "danger",
            });
        }
    }

    // ========== AUTO-REFRESH ==========
    // MODIFIÉ : Amélioration de l'auto-refresh pour maintenir les graphiques

    setupAutoRefresh() {
        if (!this.state.autoRefresh || document.hidden || !navigator.onLine) {
            return;
        }

        this.clearAutoRefresh();

        this.refreshInterval = setInterval(async () => {
            if (this.state.autoRefresh && !this.state.isLoading && !document.hidden && navigator.onLine) {
                try {
                    // S'assurer que les graphiques sont toujours présents avant le rafraîchissement
                    if (this.state.chartsEnabled && !this.state.chartsInitialized) {
                        console.log("Charts not initialized during auto-refresh, reinitializing...");
                        this.initAllCharts();
                    }
                    await this.reloadDashboard();
                } catch (error) {
                    console.error("Auto-refresh failed:", error);
                }
            }
        }, this.REFRESH_INTERVAL);
    }

    clearAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }

    toggleAutoRefresh() {
        this.state.autoRefresh = !this.state.autoRefresh;
        if (this.state.autoRefresh) {
            this.setupAutoRefresh();
        } else {
            this.clearAutoRefresh();
        }
    }

    async reloadDashboard() {
        if (this.state.isLoading) return;

        try {
            await this.fetchDataWithRetry();
        } catch (error) {
            console.error("Dashboard reload error:", error);
        }
    }

    // ========== GESTIONNAIRES D'ÉVÉNEMENTS ==========

    async onCallNext(ev) {
        ev.preventDefault();
        const ticketId = this.parseIntegerFromDataset(ev.currentTarget.dataset.ticketId);
        if (ticketId > 0) {
            await this.callNextTicket(ticketId);
        } else {
            this.notification.add("ID de ticket invalide", { type: "warning" });
        }
    }

    async onCompleteService(ev) {
        ev.preventDefault();
        const ticketId = this.parseIntegerFromDataset(ev.currentTarget.dataset.ticketId);
        if (ticketId > 0) {
            await this.completeService(ticketId);
        } else {
            this.notification.add("ID de ticket invalide", { type: "warning" });
        }
    }

    async onGenerateTicket(ev) {
        ev.preventDefault();
        const serviceId = this.parseIntegerFromDataset(ev.currentTarget.dataset.serviceId);
        if (serviceId > 0) {
            await this.generateTicket(serviceId);
        } else {
            this.notification.add("ID de service invalide", { type: "warning" });
        }
    }

    async onCallNextFromService(ev) {
        ev.preventDefault();
        const serviceId = this.parseIntegerFromDataset(ev.currentTarget.dataset.serviceId);
        if (serviceId > 0) {
            try {
                await this.executeOperation(
                    () => this.orm.call("queue.service", "action_call_next_ticket", [[serviceId]]),
                    "call_next_from_service",
                    null,
                    serviceId
                );

                this.notification.add("Prochain ticket appelé avec succès", {
                    type: "success",
                });
            } catch (error) {
                this.notification.add(`Erreur: ${this.getErrorMessage(error)}`, {
                    type: "danger",
                });
            }
        } else {
            this.notification.add("ID de service invalide", { type: "warning" });
        }
    }

    async onViewServiceDetails(ev) {
        ev.preventDefault();
        const serviceId = this.parseIntegerFromDataset(ev.currentTarget.dataset.serviceId);
        if (serviceId > 0) {
            return {
                "type": "ir.actions.act_window",
                "name": "Détails du Service",
                "res_model": "queue.service",
                "res_id": serviceId,
                "view_mode": "form",
                "target": "new"
            };
        }
    }

    async onRefreshDashboard(ev) {
        ev.preventDefault();
        await this.reloadDashboard();
    }

    onToggleAutoRefresh(ev) {
        ev.preventDefault();
        this.toggleAutoRefresh();
    }

    onToggleCharts(ev) {
        ev.preventDefault();
        //this.state.chartsEnabled = !this.state.chartsEnabled;

        if (this.state.chartsEnabled) {
            this.state.chartsInitialized = false;
            this.loadChartLibraryAndInit();
        } else {
            this.destroyAllCharts();
            this.state.chartsInitialized = false;
        }
    }

    // ========== MÉTHODES UTILITAIRES ==========

    parseIntegerFromDataset(value) {
        const parsed = parseInt(value);
        return isNaN(parsed) ? 0 : parsed;
    }

    // ========== GETTERS POUR LE TEMPLATE ==========

    get isDataLoaded() {
        return !this.state.isLoading && (
            this.state.dashboardData.services.length > 0 ||
            this.state.dashboardData.waiting_tickets.length > 0 ||
            this.state.dashboardData.serving_tickets.length > 0 ||
            Object.keys(this.state.dashboardData.stats).length > 0
        );
    }

    get dashboardData() {
        return this.state.dashboardData;
    }

    get stats() {
        return this.state.dashboardData.stats;
    }

    get lastUpdate() {
        return this.state.lastUpdate;
    }

    get isAutoRefreshEnabled() {
        return this.state.autoRefresh;
    }

    get areChartsEnabled() {
        return this.state.chartsEnabled;
    }

    get areChartsInitialized() {
        return this.state.chartsInitialized;
    }

    get isChartLibraryLoaded() {
        return this.state.chartLibraryLoaded;
    }

    get connectionStatus() {
        if (!navigator.onLine) {
            return { status: 'offline', message: 'Hors ligne' };
        }
        if (this.state.connectionError) {
            return {
                status: 'error',
                message: `Erreur de connexion (${this.state.retryAttempts}/${this.MAX_RETRY_ATTEMPTS} tentatives)`
            };
        }
        return { status: 'online', message: 'En ligne' };
    }

    get hasOperationsInProgress() {
        return this.state.operationInProgress.size > 0;
    }

    // ========== MÉTHODES DE FORMATAGE POUR LE TEMPLATE ==========

    formatTime(timeStr) {
        if (!timeStr || typeof timeStr !== 'string') return '--:--';

        try {
            const time = new Date(timeStr);
            if (!isNaN(time.getTime())) {
                return time.toLocaleTimeString();
            }
            return timeStr || '--:--';
        } catch {
            return '--:--';
        }
    }

    formatDuration(minutes) {
        const mins = parseFloat(minutes);
        if (isNaN(mins) || mins <= 0) return '0 min';

        const hours = Math.floor(mins / 60);
        const remainingMins = Math.round(mins % 60);

        if (hours > 0) {
            return `${hours}h ${remainingMins}min`;
        }
        return `${remainingMins} min`;
    }

    getStatusColor(state) {
        const colors = {
            'waiting': 'warning',
            'called': 'info',
            'serving': 'primary',
            'served': 'success',
            'cancelled': 'secondary',
            'no_show': 'danger'
        };
        return colors[state] || 'secondary';
    }

    getPriorityColor(priority) {
        const colors = {
            'normal': 'secondary',
            'high': 'warning',
            'urgent': 'danger'
        };
        return colors[priority] || 'secondary';
    }

    getConnectionStatusColor() {
        const status = this.connectionStatus.status;
        const colors = {
            'online': 'success',
            'offline': 'danger',
            'error': 'warning'
        };
        return colors[status] || 'secondary';
    }

    // ========== HELPER POUR DÉBOGAGE ==========

    logState() {
        console.log("Dashboard State:", {
            isLoading: this.state.isLoading,
            connectionError: this.state.connectionError,
            retryAttempts: this.state.retryAttempts,
            autoRefresh: this.state.autoRefresh,
            chartsEnabled: this.state.chartsEnabled,
            chartsInitialized: this.state.chartsInitialized,
            chartLibraryLoaded: this.state.chartLibraryLoaded,
            chartsCreationInProgress: this.state.chartsCreationInProgress,
            operationsInProgress: Array.from(this.state.operationInProgress),
            dataLoaded: this.isDataLoaded,
            online: navigator.onLine,
            chartInstances: Object.keys(this.charts).reduce((acc, key) => {
                acc[key] = !!this.charts[key];
                return acc;
            }, {})
        });
    }
}

// Enregistrer le composant dans le registre des actions
registry.category("actions").add("queue_dashboard_action", QueueDashboard);

export { QueueDashboard };