import { Component, onWillDestroy, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const REFRESH_MS = 5000;

/**
 * Tableau de bord de supervision temps réel d'un site :
 * KPIs du jour, état des files (prochain numéro, ETA) et des guichets.
 * Les données viennent de queue.location.get_dashboard_data (sans sudo :
 * un responsable ne voit que ses établissements), re-sondées toutes les 5 s.
 */
export class QueueDashboard extends Component {
    static template = "queue_management.QueueDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            error: false,
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
}

registry.category("actions").add("queue_management.dashboard", QueueDashboard);
