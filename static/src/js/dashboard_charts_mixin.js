/** @odoo-module **/

/**
 * Mixin simplifié pour la gestion des graphiques Chart.js dans les dashboards Odoo
 * Version allégée qui se concentre sur l'essentiel
 * 
 * UTILISATION:
 * 1. Ce mixin n'est plus nécessaire avec la nouvelle implémentation
 * 2. La gestion des graphiques est maintenant intégrée directement dans le composant principal
 * 3. Ce fichier est conservé pour la compatibilité si nécessaire
 */
export const DashboardChartsFixes = {
    /**
     * Méthode de compatibilité - ne fait plus rien
     * La fonctionnalité est maintenant dans le composant principal
     */
    initAllCharts() {
        console.warn("DashboardChartsFixes.initAllCharts() is deprecated. Charts are now managed directly in the component.");
        // Ne fait plus rien - la logique est dans le composant principal
    },

    /**
     * Méthode de compatibilité - ne fait plus rien
     */
    updateAllCharts() {
        console.warn("DashboardChartsFixes.updateAllCharts() is deprecated. Charts are now managed directly in the component.");
        // Ne fait plus rien - la logique est dans le composant principal
    },

    /**
     * Méthode de compatibilité - ne fait plus rien
     */
    destroyAllCharts() {
        console.warn("DashboardChartsFixes.destroyAllCharts() is deprecated. Charts are now managed directly in the component.");
        // Ne fait plus rien - la logique est dans le composant principal
    },

    /**
     * Méthode de compatibilité - ne fait plus rien
     */
    resizeAllCharts() {
        console.warn("DashboardChartsFixes.resizeAllCharts() is deprecated. Charts are now managed directly in the component.");
        // Ne fait plus rien - la logique est dans le composant principal
    }
};