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