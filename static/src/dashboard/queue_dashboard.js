import { Component, onWillDestroy, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const REFRESH_MS = 5000;

// Seuils d'alerte visuels sur les files (rendus configurables en Phase I).
const WAITING_WARN = 4;
const WAITING_DANGER = 8;
const ETA_WARN = 15; // minutes
const ETA_DANGER = 30;

/**
 * Tableau de bord temps réel d'un site — et poste de travail : les cartes
 * guichets portent les actions (appeler / démarrer / terminer / absent).
 * Données via queue.location.get_dashboard_data (sans sudo : les record
 * rules multi-société s'appliquent), re-sondées toutes les 5 s.
 */
export class QueueDashboard extends Component {
    static template = "queue_management.QueueDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            error: false,
            acting: false,
            locationId: false,
            locations: [],
            kpis: null,
            services: [],
            counters: [],
        });
        onWillStart(() => this.load());
        this.timer = setInterval(() => this.load(), REFRESH_MS);
        onWillDestroy(() => clearInterval(this.timer));
    }

    async load() {
        try {
            const data = await this.orm.call(
                "queue.location",
                "get_dashboard_data",
                [this.state.locationId]
            );
            this.state.locations = data.locations;
            this.state.locationId = data.location_id;
            this.state.kpis = data.kpis || null;
            this.state.services = data.services || [];
            this.state.counters = data.counters || [];
            this.state.error = false;
        } catch {
            // Erreur transitoire (réseau…) : on garde les dernières données
            // affichées et on retentera au prochain tick.
            this.state.error = true;
        } finally {
            this.state.loading = false;
        }
    }

    onSelectLocation(ev) {
        this.state.locationId = parseInt(ev.target.value, 10) || false;
        this.state.loading = true;
        this.load();
    }

    /** Classe d'alerte d'une file selon l'affluence et l'attente estimée. */
    serviceAlertClass(svc) {
        if (svc.waiting >= WAITING_DANGER || svc.eta_next >= ETA_DANGER) {
            return "table-danger";
        }
        if (svc.waiting >= WAITING_WARN || svc.eta_next >= ETA_WARN) {
            return "table-warning";
        }
        return "";
    }

    /** Exécute une action de guichet puis rafraîchit immédiatement. */
    async counterAction(counterId, method) {
        if (this.state.acting) {
            return;
        }
        this.state.acting = true;
        try {
            await this.orm.call("queue.counter", method, [[counterId]]);
            await this.load();
        } catch (error) {
            // UserError métier (« Aucun client en attente »…) : notification
            // native, le dashboard reste en place.
            this.notification.add(
                error.data?.message || error.message || "Action impossible.",
                { type: "warning" }
            );
        } finally {
            this.state.acting = false;
        }
    }
}

registry.category("actions").add("queue_management.dashboard", QueueDashboard);
