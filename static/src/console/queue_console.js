import { Component, onWillDestroy, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const REFRESH_MS = 3000;

/**
 * « Ma console » — le poste de travail plein écran de l'agent : il se
 * connecte à un guichet (présence partagée possible : binôme, formation),
 * voit le ticket en cours en très grand et agit en un geste.
 * Données via queue.counter.get_console_data (sans sudo : record rules).
 */
export class QueueConsole extends Component {
    static template = "queue_management.QueueConsole";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            acting: false,
            counterId: false,
            counters: [],
            data: {},
        });
        onWillStart(() => this.load());
        this.timer = setInterval(() => this.load(), REFRESH_MS);
        onWillDestroy(() => clearInterval(this.timer));
    }

    async load() {
        try {
            const data = await this.orm.call(
                "queue.counter", "get_console_data", [this.state.counterId]);
            this.state.counters = data.counters;
            this.state.counterId = data.counter_id;
            this.state.data = data;
        } catch {
            // transitoire : on garde l'affichage courant
        } finally {
            this.state.loading = false;
        }
    }

    onSelectCounter(ev) {
        this.state.counterId = parseInt(ev.target.value, 10) || false;
        this.load();
    }

    async act(method) {
        if (this.state.acting || !this.state.counterId) {
            return;
        }
        this.state.acting = true;
        try {
            await this.orm.call("queue.counter", method, [[this.state.counterId]]);
            await this.load();
        } catch (error) {
            this.notification.add(
                error.data?.message || error.message || "Action impossible.",
                { type: "warning" });
        } finally {
            this.state.acting = false;
        }
    }
}

registry.category("actions").add("queue_management.console", QueueConsole);
