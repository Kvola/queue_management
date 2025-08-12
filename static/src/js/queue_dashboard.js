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
            isLoading: true
        });

        this.refreshInterval = null;

        onWillStart(async () => {
            await this.fetchData();
        });

        onMounted(() => {
            this.setupAutoRefresh();
        });

        onWillUnmount(() => {
            if (this.refreshInterval) {
                clearInterval(this.refreshInterval);
                this.refreshInterval = null;
            }
        });
    }

    async fetchData() {
        try {
            this.state.isLoading = true;
            const result = await this.orm.call("queue.service", "get_dashboard_data", []);
            
            // S'assurer que les données sont dans le bon format
            this.state.dashboardData = {
                services: result.services || [],
                waiting_tickets: result.waiting_tickets || [],
                serving_tickets: result.serving_tickets || [],
                stats: result.stats || {}
            };
        } catch (error) {
            this.notification.add("Erreur lors du chargement des données", {
                type: "danger",
            });
            console.error("Fetch data error:", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    async callNextTicket(ticketId) {
        try {
            await this.orm.call("queue.ticket", "action_call_next", [[ticketId]]);
            await this.reloadDashboard();
            this.notification.add("Ticket appelé avec succès", {
                type: "success",
            });
        } catch (error) {
            this.notification.add("Erreur lors de l'appel du ticket", {
                type: "danger",
            });
            console.error("Call next ticket error:", error);
        }
    }

    async completeService(ticketId) {
        try {
            await this.orm.call("queue.ticket", "action_complete_service", [[ticketId]]);
            await this.reloadDashboard();
            this.notification.add("Service terminé avec succès", {
                type: "success",
            });
        } catch (error) {
            this.notification.add("Erreur lors de la completion du service", {
                type: "danger",
            });
            console.error("Complete service error:", error);
        }
    }

    async generateTicket(serviceId) {
        try {
            await this.orm.call("queue.service", "generate_ticket", [[serviceId]]);
            await this.reloadDashboard();
            this.notification.add("Ticket généré avec succès", {
                type: "success",
            });
        } catch (error) {
            this.notification.add("Erreur lors de la génération du ticket", {
                type: "danger",
            });
            console.error("Generate ticket error:", error);
        }
    }

    setupAutoRefresh() {
        // Refresh toutes les 15 secondes
        this.refreshInterval = setInterval(async () => {
            await this.reloadDashboard();
        }, 15000);
    }

    async reloadDashboard() {
        await this.fetchData();
    }

    // Méthodes appelées depuis le template
    async onCallNext(ev) {
        const ticketId = parseInt(ev.currentTarget.dataset.ticketId);
        await this.callNextTicket(ticketId);
    }

    async onCompleteService(ev) {
        const ticketId = parseInt(ev.currentTarget.dataset.ticketId);
        await this.completeService(ticketId);
    }

    async onGenerateTicket(ev) {
        const serviceId = parseInt(ev.currentTarget.dataset.serviceId);
        await this.generateTicket(serviceId);
    }

    // Getters pour le template
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
}

// Enregistrer le composant dans le registre des actions
registry.category("actions").add("queue_dashboard_action", QueueDashboard);