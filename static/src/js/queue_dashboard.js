/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class QueueDashboard extends Component {
    static template = "queue_management.QueueDashboardMain";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        
        this.state = useState({
            dashboardData: {
                services: [],
                waiting_tickets: [],
                serving_tickets: [],
                stats: {}
            },
            isLoading: true,
            lastUpdate: null,
            autoRefresh: true,
            connectionError: false,
            retryAttempts: 0,
            operationInProgress: new Set() // Track ongoing operations
        });

        this.refreshInterval = null;
        this.retryTimeout = null;
        this.MAX_RETRY_ATTEMPTS = 3;
        this.RETRY_DELAY_BASE = 2000; // Base delay for exponential backoff
        this.REFRESH_INTERVAL = 15000;
        this.REQUEST_TIMEOUT = 30000; // 30 seconds timeout

        // Bind methods to preserve context
        this.handleVisibilityChange = this.handleVisibilityChange.bind(this);
        this.handleOnlineStatus = this.handleOnlineStatus.bind(this);

        onWillStart(async () => {
            await this.initializeDashboard();
        });

        onMounted(() => {
            this.setupEventListeners();
            this.setupAutoRefresh();
        });

        onWillUnmount(() => {
            this.cleanup();
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
        // Listen for page visibility changes to pause/resume refresh
        document.addEventListener('visibilitychange', this.handleVisibilityChange);
        
        // Listen for online/offline events
        window.addEventListener('online', this.handleOnlineStatus);
        window.addEventListener('offline', this.handleOnlineStatus);
    }

    handleVisibilityChange() {
        if (document.hidden) {
            this.clearAutoRefresh();
        } else if (this.state.autoRefresh) {
            this.setupAutoRefresh();
            // Refresh data when page becomes visible again
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

    cleanup() {
        this.clearAutoRefresh();
        this.clearRetryTimeout();
        document.removeEventListener('visibilitychange', this.handleVisibilityChange);
        window.removeEventListener('online', this.handleOnlineStatus);
        window.removeEventListener('offline', this.handleOnlineStatus);
    }

    clearRetryTimeout() {
        if (this.retryTimeout) {
            clearTimeout(this.retryTimeout);
            this.retryTimeout = null;
        }
    }

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

                // Exponential backoff
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
            
            // Add timeout to the request
            const timeoutPromise = new Promise((_, reject) => 
                setTimeout(() => reject(new Error("Request timeout")), this.REQUEST_TIMEOUT)
            );

            const dataPromise = this.orm.call("queue.service", "get_dashboard_data", []);
            const result = await Promise.race([dataPromise, timeoutPromise]);
            
            // Enhanced data validation
            this.validateAndSetData(result);
            
        } catch (error) {
            console.error("Dashboard fetch error:", error);
            this.handleFetchError(error);
            throw error;
        } finally {
            this.state.isLoading = false;
        }
    }

    validateAndSetData(result) {
        if (!result || typeof result !== 'object') {
            throw new Error("Invalid response format");
        }

        try {
            // Validation et formatage des données avec vérifications strictes
            this.state.dashboardData = {
                services: this.validateServices(result.services),
                waiting_tickets: this.validateTickets(result.waiting_tickets),
                serving_tickets: this.validateTickets(result.serving_tickets),
                stats: this.validateStats(result.stats)
            };
            
            this.state.lastUpdate = this.validateTimestamp(result.last_update) || new Date().toLocaleTimeString();
            
        } catch (validationError) {
            console.error("Data validation error:", validationError);
            throw new Error(`Data validation failed: ${validationError.message}`);
        }
    }

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
                // Return a safe default service object
                return this.getDefaultService(service?.id || index);
            }
        }).filter(Boolean); // Remove any null/undefined services
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
                // Return a safe default ticket object
                return this.getDefaultTicket(ticket?.id || index);
            }
        }).filter(Boolean); // Remove any null/undefined tickets
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

    // Utility validation methods
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

    // Default object creators
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

    handleFetchError(error) {
        const errorMessage = this.getErrorMessage(error);
        
        this.notification.add(`Erreur de connexion: ${errorMessage}`, {
            type: "danger",
            sticky: this.state.retryAttempts >= this.MAX_RETRY_ATTEMPTS
        });

        // Reset to safe default data if we can't fetch
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
            stats: this.getDefaultStats()
        };
    }

    // Enhanced operation methods with better error handling
    async executeOperation(operation, operationName, ticketId = null, serviceId = null) {
        const operationKey = `${operationName}_${ticketId || serviceId || Date.now()}`;
        
        // Prevent duplicate operations
        if (this.state.operationInProgress.has(operationKey)) {
            console.warn(`Operation ${operationName} already in progress`);
            return;
        }

        try {
            this.state.operationInProgress.add(operationKey);
            
            const result = await operation();
            
            // Always reload dashboard after successful operations
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

    setupAutoRefresh() {
        if (!this.state.autoRefresh || document.hidden || !navigator.onLine) {
            return;
        }
        
        this.clearAutoRefresh(); // Clear any existing interval
        
        this.refreshInterval = setInterval(async () => {
            if (this.state.autoRefresh && !this.state.isLoading && !document.hidden && navigator.onLine) {
                try {
                    await this.reloadDashboard();
                } catch (error) {
                    console.error("Auto-refresh failed:", error);
                    // Don't show notification for auto-refresh failures to avoid spam
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
        // Éviter les rechargements multiples simultanés
        if (this.state.isLoading) return;
        
        try {
            await this.fetchDataWithRetry();
        } catch (error) {
            console.error("Dashboard reload error:", error);
            // Error is already handled in fetchDataWithRetry
        }
    }

    // Enhanced event handlers with better validation
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

    // Utility methods
    parseIntegerFromDataset(value) {
        const parsed = parseInt(value);
        return isNaN(parsed) ? 0 : parsed;
    }

    // Enhanced getters for the template
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

    get connectionStatus() {
        if (!navigator.onLine) {
            return { status: 'offline', message: 'Hors ligne' };
        }
        if (this.state.connectionError) {
            return { status: 'error', message: `Erreur de connexion (${this.state.retryAttempts}/${this.MAX_RETRY_ATTEMPTS} tentatives)` };
        }
        return { status: 'online', message: 'En ligne' };
    }

    get hasOperationsInProgress() {
        return this.state.operationInProgress.size > 0;
    }

    // Enhanced utility methods for the template
    formatTime(timeStr) {
        if (!timeStr || typeof timeStr !== 'string') return '--:--';
        
        try {
            // Handle various time formats
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

    // Debug helper (can be removed in production)
    logState() {
        console.log("Dashboard State:", {
            isLoading: this.state.isLoading,
            connectionError: this.state.connectionError,
            retryAttempts: this.state.retryAttempts,
            autoRefresh: this.state.autoRefresh,
            operationsInProgress: Array.from(this.state.operationInProgress),
            dataLoaded: this.isDataLoaded,
            online: navigator.onLine
        });
    }
}

// Enregistrer le composant dans le registre des actions
registry.category("actions").add("queue_dashboard_action", QueueDashboard);