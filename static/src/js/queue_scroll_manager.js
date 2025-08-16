/**
 * GESTIONNAIRE DE SCROLL POUR LES TEMPLATES
 * Système de Files d'Attente - Queue Management
 * 
 * Ce script garantit que le scroll fonctionne sur tous les templates
 * et corrige les problèmes dynamiques qui peuvent survenir
 */

(function() {
    'use strict';

    // Configuration
    const SCROLL_CONFIG = {
        enableSmoothScroll: true,
        enableScrollIndicator: true,
        debugMode: false,
        autoFixInterval: 5000, // Vérification automatique toutes les 5 secondes
        mobileBreakpoint: 768
    };

    /**
     * Classe principale pour gérer le scroll
     */
    class QueueScrollManager {
        constructor() {
            this.init();
        }

        init() {
            this.waitForDOM(() => {
                this.fixScrollIssues();
                this.setupScrollIndicator();
                this.setupEventListeners();
                this.startAutoFix();
                
                if (SCROLL_CONFIG.debugMode) {
                    console.log('QueueScrollManager initialisé');
                }
            });
        }

        /**
         * Attendre que le DOM soit prêt
         */
        waitForDOM(callback) {
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', callback);
            } else {
                callback();
            }
        }

        /**
         * Corriger les problèmes de scroll principaux
         */
        fixScrollIssues() {
            // 1. Forcer le scroll sur html et body
            this.forceScrollOnRoot();
            
            // 2. Corriger les containers problématiques
            this.fixContainers();
            
            // 3. Corriger les éléments sticky
            this.fixStickyElements();
            
            // 4. Corriger les hauteurs fixes
            this.fixFixedHeights();
            
            // 5. Corriger les modales
            this.fixModals();

            if (SCROLL_CONFIG.debugMode) {
                console.log('Problèmes de scroll corrigés');
            }
        }

        /**
         * Forcer le scroll sur les éléments racines
         */
        forceScrollOnRoot() {
            const html = document.documentElement;
            const body = document.body;

            // Styles CSS via JavaScript
            const rootStyles = {
                'overflow-y': 'scroll',
                'scroll-behavior': 'smooth',
                'height': 'auto',
                'min-height': '100%'
            };

            Object.assign(html.style, rootStyles);
            Object.assign(body.style, {
                ...rootStyles,
                'min-height': '100vh',
                'position': 'relative'
            });
        }

        /**
         * Corriger les containers
         */
        fixContainers() {
            const selectors = [
                '#wrap',
                '.o_main_content',
                'main',
                '.container',
                '.container-fluid'
            ];

            selectors.forEach(selector => {
                const elements = document.querySelectorAll(selector);
                elements.forEach(element => {
                    element.style.overflow = 'visible';
                    element.style.minHeight = 'auto';
                    element.style.height = 'auto';
                    element.style.maxHeight = 'none';
                });
            });
        }

        /**
         * Corriger les éléments sticky problématiques
         */
        fixStickyElements() {
            const stickyElements = document.querySelectorAll('.sticky-top');
            
            stickyElements.forEach(element => {
                // Sur mobile, désactiver le sticky
                if (this.isMobile()) {
                    element.style.position = 'relative';
                    element.style.top = 'auto';
                } else {
                    // Sur desktop, limiter la hauteur
                    element.style.maxHeight = 'calc(100vh - 40px)';
                    element.style.overflowY = 'auto';
                }
            });
        }

        /**
         * Corriger les hauteurs fixes qui empêchent le scroll
         */
        fixFixedHeights() {
            // Éléments avec hauteur fixe problématique
            const problematicSelectors = [
                '[style*="height: 100vh"]',
                '[style*="max-height: 100vh"]',
                '.h-100[style*="overflow: hidden"]'
            ];

            problematicSelectors.forEach(selector => {
                const elements = document.querySelectorAll(selector);
                elements.forEach(element => {
                    if (this.shouldFixHeight(element)) {
                        element.style.height = 'auto';
                        element.style.minHeight = element.style.height;
                        element.style.overflow = 'visible';
                    }
                });
            });
        }

        /**
         * Déterminer si un élément doit être corrigé
         */
        shouldFixHeight(element) {
            // Ne pas corriger les éléments d'impression ou les modales
            return !element.closest('.modal') && 
                   !element.closest('[class*="print"]') &&
                   !element.classList.contains('no-scroll-fix');
        }

        /**
         * Corriger les modales
         */
        fixModals() {
            const modals = document.querySelectorAll('.modal');
            modals.forEach(modal => {
                modal.style.overflowY = 'auto';
                
                const modalBody = modal.querySelector('.modal-body');
                if (modalBody) {
                    modalBody.style.maxHeight = 'calc(100vh - 200px)';
                    modalBody.style.overflowY = 'auto';
                }
            });
        }

        /**
         * Configuration de l'indicateur de scroll
         */
        setupScrollIndicator() {
            if (!SCROLL_CONFIG.enableScrollIndicator) return;

            // Créer l'indicateur s'il n'existe pas
            let indicator = document.getElementById('scroll-indicator');
            if (!indicator) {
                indicator = document.createElement('div');
                indicator.id = 'scroll-indicator';
                indicator.className = 'scroll-indicator';
                document.body.appendChild(indicator);
            }

            // Mettre à jour l'indicateur au scroll
            this.updateScrollIndicator();
        }

        /**
         * Mettre à jour l'indicateur de scroll
         */
        updateScrollIndicator() {
            const indicator = document.getElementById('scroll-indicator');
            if (!indicator) return;

            const updateProgress = () => {
                const scrolled = window.scrollY;
                const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
                const progress = maxScroll > 0 ? scrolled / maxScroll : 0;
                
                indicator.style.setProperty('--scroll-progress', progress);
                indicator.classList.toggle('active', progress > 0);
            };

            // Mise à jour immédiate
            updateProgress();

            // Mise à jour au scroll
            let ticking = false;
            window.addEventListener('scroll', () => {
                if (!ticking) {
                    requestAnimationFrame(() => {
                        updateProgress();
                        ticking = false;
                    });
                    ticking = true;
                }
            }, { passive: true });
        }

        /**
         * Configuration des événements
         */
        setupEventListeners() {
            // Recorriger après redimensionnement
            let resizeTimer;
            window.addEventListener('resize', () => {
                clearTimeout(resizeTimer);
                resizeTimer = setTimeout(() => {
                    this.fixScrollIssues();
                }, 250);
            });

            // Correction après navigation AJAX
            if (typeof odoo !== 'undefined' && odoo.define) {
                this.setupOdooEvents();
            }

            // Correction après ajout dynamique de contenu
            this.observeContentChanges();
        }

        /**
         * Configuration des événements Odoo
         */
        setupOdooEvents() {
            odoo.define('queue_management.scroll_fix', (require) => {
                const publicWidget = require('web.public.widget');

                publicWidget.registry.ScrollFix = publicWidget.Widget.extend({
                    selector: 'body',
                    
                    start: function () {
                        this._super.apply(this, arguments);
                        // Recorriger après chargement du widget
                        setTimeout(() => this._fixScroll(), 100);
                    },

                    _fixScroll: function () {
                        if (window.queueScrollManager) {
                            window.queueScrollManager.fixScrollIssues();
                        }
                    }
                });

                return publicWidget.registry.ScrollFix;
            });
        }

        /**
         * Observer les changements de contenu
         */
        observeContentChanges() {
            if (!window.MutationObserver) return;

            const observer = new MutationObserver((mutations) => {
                let shouldFix = false;
                
                mutations.forEach((mutation) => {
                    // Vérifier s'il y a eu des ajouts d'éléments
                    if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                        shouldFix = true;
                    }
                    
                    // Vérifier les changements d'attributs style
                    if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
                        shouldFix = true;
                    }
                });

                if (shouldFix) {
                    // Correction différée pour éviter trop d'appels
                    clearTimeout(this.fixTimeout);
                    this.fixTimeout = setTimeout(() => {
                        this.fixScrollIssues();
                    }, 500);
                }
            });

            // Observer le body et ses enfants
            observer.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['style', 'class']
            });
        }

        /**
         * Démarrer la correction automatique périodique
         */
        startAutoFix() {
            if (SCROLL_CONFIG.autoFixInterval <= 0) return;

            setInterval(() => {
                this.fixScrollIssues();
                
                if (SCROLL_CONFIG.debugMode) {
                    console.log('Auto-correction du scroll effectuée');
                }
            }, SCROLL_CONFIG.autoFixInterval);
        }

        /**
         * Vérifier si on est sur mobile
         */
        isMobile() {
            return window.innerWidth < SCROLL_CONFIG.mobileBreakpoint;
        }

        /**
         * Méthodes utilitaires publiques
         */
        
        /**
         * Scroller vers un élément
         */
        scrollToElement(selector, offset = 0) {
            const element = document.querySelector(selector);
            if (element) {
                const top = element.offsetTop - offset;
                window.scrollTo({
                    top: top,
                    behavior: 'smooth'
                });
            }
        }

        /**
         * Scroller vers le haut
         */
        scrollToTop() {
            window.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        }

        /**
         * Activer/désactiver le mode debug
         */
        setDebugMode(enabled) {
            SCROLL_CONFIG.debugMode = enabled;
            
            if (enabled) {
                document.body.classList.add('scroll-debug');
                console.log('Mode debug du scroll activé');
            } else {
                document.body.classList.remove('scroll-debug');
            }
        }

        /**
         * Forcer une correction manuelle
         */
        forceFix() {
            this.fixScrollIssues();
            console.log('Correction manuelle du scroll appliquée');
        }
    }

    /**
     * Utilitaires globaux
     */
    
    // Fonction helper pour corriger le scroll d'un élément spécifique
    window.fixElementScroll = function(selector) {
        const elements = document.querySelectorAll(selector);
        elements.forEach(element => {
            element.style.overflow = 'auto';
            element.style.height = 'auto';
            element.style.maxHeight = 'none';
        });
    };

    // Fonction helper pour les templates
    window.ensureTemplateScroll = function() {
        if (window.queueScrollManager) {
            window.queueScrollManager.forceFix();
        }
    };

    /**
     * Initialisation
     */
    
    // Créer l'instance globale
    window.queueScrollManager = new QueueScrollManager();

    // Exposer les utilitaires pour les templates
    window.QueueScrollUtils = {
        scrollToTop: () => window.queueScrollManager.scrollToTop(),
        scrollToElement: (selector, offset) => window.queueScrollManager.scrollToElement(selector, offset),
        forceFix: () => window.queueScrollManager.forceFix(),
        setDebugMode: (enabled) => window.queueScrollManager.setDebugMode(enabled)
    };

    // Debug en mode développement
    if (window.location.hostname === 'localhost' || window.location.search.includes('debug=1')) {
        window.queueScrollManager.setDebugMode(true);
        
        // Commandes console pour debug
        window.scrollDebug = {
            fix: () => window.queueScrollManager.forceFix(),
            debug: (enabled) => window.queueScrollManager.setDebugMode(enabled),
            info: () => {
                console.log('Scroll Debug Info:');
                console.log('- Hauteur document:', document.documentElement.scrollHeight);
                console.log('- Hauteur viewport:', window.innerHeight);
                console.log('- Position scroll:', window.scrollY);
                console.log('- Scroll possible:', document.documentElement.scrollHeight > window.innerHeight);
            }
        };
    }

})();