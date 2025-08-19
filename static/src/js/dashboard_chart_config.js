/** @odoo-module **/
// Configuration des graphiques Chart.js pour le Dashboard Queue Management

export const ChartConfig = {
    // Couleurs par défaut pour les graphiques
    colors: {
        primary: 'rgba(0, 123, 255, 0.8)',
        success: 'rgba(40, 167, 69, 0.8)',
        warning: 'rgba(255, 193, 7, 0.8)',
        danger: 'rgba(220, 53, 69, 0.8)',
        info: 'rgba(23, 162, 184, 0.8)',
        secondary: 'rgba(108, 117, 125, 0.8)',
        light: 'rgba(248, 249, 250, 0.8)',
        dark: 'rgba(52, 58, 64, 0.8)',
        
        // Versions avec bordures
        primaryBorder: 'rgba(0, 123, 255, 1)',
        successBorder: 'rgba(40, 167, 69, 1)',
        warningBorder: 'rgba(255, 193, 7, 1)',
        dangerBorder: 'rgba(220, 53, 69, 1)',
        infoBorder: 'rgba(23, 162, 184, 1)',
        secondaryBorder: 'rgba(108, 117, 125, 1)',
        lightBorder: 'rgba(248, 249, 250, 1)',
        darkBorder: 'rgba(52, 58, 64, 1)',
        
        // Palette étendue pour plus de services
        palette: [
            'rgba(0, 123, 255, 0.8)',   // Bleu
            'rgba(40, 167, 69, 0.8)',   // Vert
            'rgba(255, 193, 7, 0.8)',   // Jaune
            'rgba(220, 53, 69, 0.8)',   // Rouge
            'rgba(23, 162, 184, 0.8)',  // Cyan
            'rgba(108, 117, 125, 0.8)', // Gris
            'rgba(102, 16, 242, 0.8)',  // Violet
            'rgba(255, 99, 132, 0.8)',  // Rose
            'rgba(54, 162, 235, 0.8)',  // Bleu clair
            'rgba(255, 159, 64, 0.8)',  // Orange
        ],
        
        paletteBorder: [
            'rgba(0, 123, 255, 1)',
            'rgba(40, 167, 69, 1)',
            'rgba(255, 193, 7, 1)',
            'rgba(220, 53, 69, 1)',
            'rgba(23, 162, 184, 1)',
            'rgba(108, 117, 125, 1)',
            'rgba(102, 16, 242, 1)',
            'rgba(255, 99, 132, 1)',
            'rgba(54, 162, 235, 1)',
            'rgba(255, 159, 64, 1)',
        ]
    },

    // Configuration par défaut pour tous les graphiques
    defaultOptions: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                labels: {
                    usePointStyle: true,
                    padding: 20,
                    font: {
                        size: 12,
                        family: "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif"
                    }
                }
            },
            tooltip: {
                backgroundColor: 'rgba(0, 0, 0, 0.8)',
                titleColor: '#ffffff',
                bodyColor: '#ffffff',
                borderColor: 'rgba(255, 255, 255, 0.2)',
                borderWidth: 1,
                cornerRadius: 8,
                displayColors: true,
                titleFont: {
                    size: 14,
                    weight: 'bold'
                },
                bodyFont: {
                    size: 12
                },
                padding: 12
            }
        },
        animation: {
            duration: 1500,
            easing: 'easeInOutCubic'
        }
    },

    // Configuration spécifique pour les graphiques en barres
    barChartOptions: {
        scales: {
            x: {
                grid: {
                    display: false
                },
                ticks: {
                    font: {
                        size: 11
                    },
                    maxRotation: 45,
                    minRotation: 0
                }
            },
            y: {
                beginAtZero: true,
                grid: {
                    color: 'rgba(0, 0, 0, 0.1)',
                    lineWidth: 1
                },
                ticks: {
                    stepSize: 1,
                    font: {
                        size: 11
                    },
                    callback: function(value) {
                        return Number.isInteger(value) ? value : '';
                    }
                }
            }
        },
        plugins: {
            legend: {
                position: 'top'
            }
        }
    },

    // Configuration spécifique pour les graphiques circulaires
    doughnutChartOptions: {
        cutout: '60%',
        plugins: {
            legend: {
                position: 'right',
                labels: {
                    generateLabels: function(chart) {
                        const data = chart.data;
                        if (data.labels.length && data.datasets.length) {
                            const dataset = data.datasets[0];
                            return data.labels.map((label, i) => {
                                const value = dataset.data[i];
                                const total = dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((value / total) * 100).toFixed(1);
                                
                                return {
                                    text: `${label}: ${value} (${percentage}%)`,
                                    fillStyle: dataset.backgroundColor[i],
                                    strokeStyle: dataset.borderColor[i],
                                    lineWidth: dataset.borderWidth,
                                    hidden: false,
                                    index: i
                                };
                            });
                        }
                        return [];
                    }
                }
            },
            tooltip: {
                callbacks: {
                    label: function(context) {
                        const label = context.label || '';
                        const value = context.raw;
                        const total = context.dataset.data.reduce((a, b) => a + b, 0);
                        const percentage = ((value / total) * 100).toFixed(1);
                        return `${label}: ${value} tickets (${percentage}%)`;
                    }
                }
            }
        }
    },

    // Configuration spécifique pour les graphiques linéaires
    lineChartOptions: {
        elements: {
            line: {
                tension: 0.4,
                borderWidth: 3
            },
            point: {
                radius: 6,
                hoverRadius: 8,
                borderWidth: 2
            }
        },
        scales: {
            x: {
                grid: {
                    display: false
                },
                ticks: {
                    font: {
                        size: 11
                    }
                }
            },
            y: {
                beginAtZero: true,
                grid: {
                    color: 'rgba(0, 0, 0, 0.1)',
                    lineWidth: 1
                },
                ticks: {
                    font: {
                        size: 11
                    },
                    callback: function(value) {
                        return value + ' min';
                    }
                }
            }
        },
        plugins: {
            legend: {
                display: false
            },
            tooltip: {
                callbacks: {
                    label: function(context) {
                        return `${context.dataset.label}: ${context.raw} minutes`;
                    }
                }
            }
        }
    },

    // Configuration pour les graphiques de performance avec seuils
    performanceChartOptions: {
        scales: {
            x: {
                grid: {
                    display: false
                },
                ticks: {
                    font: {
                        size: 11
                    },
                    maxRotation: 45
                }
            },
            y: {
                beginAtZero: true,
                max: 100,
                grid: {
                    color: 'rgba(0, 0, 0, 0.1)'
                },
                ticks: {
                    font: {
                        size: 11
                    },
                    callback: function(value) {
                        return value + '%';
                    }
                }
            }
        },
        plugins: {
            legend: {
                display: false
            },
            tooltip: {
                callbacks: {
                    label: function(context) {
                        const value = context.raw;
                        let status = 'Normal';
                        if (value > 80) status = 'Critique';
                        else if (value > 60) status = 'Élevé';
                        
                        return `${context.label}: ${value}% (${status})`;
                    }
                }
            },
            // Plugin personnalisé pour les lignes de seuil
            annotation: {
                annotations: {
                    line1: {
                        type: 'line',
                        yMin: 60,
                        yMax: 60,
                        borderColor: 'rgba(255, 193, 7, 0.8)',
                        borderWidth: 2,
                        borderDash: [5, 5],
                        label: {
                            content: 'Seuil d\'alerte (60%)',
                            enabled: true,
                            position: 'end'
                        }
                    },
                    line2: {
                        type: 'line',
                        yMin: 80,
                        yMax: 80,
                        borderColor: 'rgba(220, 53, 69, 0.8)',
                        borderWidth: 2,
                        borderDash: [5, 5],
                        label: {
                            content: 'Seuil critique (80%)',
                            enabled: true,
                            position: 'end'
                        }
                    }
                }
            }
        }
    },

    // Utilitaires pour générer les configurations
    utils: {
        // Génère une couleur basée sur l'index
        getColor: function(index, alpha = 0.8) {
            const colors = this.colors.palette;
            const color = colors[index % colors.length];
            if (alpha !== 0.8) {
                return color.replace('0.8', alpha.toString());
            }
            return color;
        },

        // Génère une couleur de bordure basée sur l'index
        getBorderColor: function(index) {
            const colors = this.colors.paletteBorder;
            return colors[index % colors.length];
        },

        // Génère un gradient pour les arrière-plans
        createGradient: function(ctx, color1, color2, direction = 'vertical') {
            let gradient;
            if (direction === 'vertical') {
                gradient = ctx.createLinearGradient(0, 0, 0, 400);
            } else {
                gradient = ctx.createLinearGradient(0, 0, 400, 0);
            }
            gradient.addColorStop(0, color1);
            gradient.addColorStop(1, color2);
            return gradient;
        },

        // Formate les tooltips pour les temps
        formatTimeTooltip: function(value, unit = 'min') {
            if (value === 0) return '0 ' + unit;
            if (value < 1 && unit === 'min') return (value * 60).toFixed(0) + ' sec';
            if (value >= 60 && unit === 'min') {
                const hours = Math.floor(value / 60);
                const minutes = Math.round(value % 60);
                return `${hours}h ${minutes}min`;
            }
            return value.toFixed(1) + ' ' + unit;
        },

        // Génère des datasets pour plusieurs séries
        generateDatasets: function(labels, seriesData, seriesNames, type = 'bar') {
            const datasets = [];
            
            seriesData.forEach((data, index) => {
                const dataset = {
                    label: seriesNames[index] || `Série ${index + 1}`,
                    data: data,
                    backgroundColor: this.getColor(index),
                    borderColor: this.getBorderColor(index),
                    borderWidth: type === 'line' ? 3 : 2
                };

                if (type === 'line') {
                    dataset.fill = false;
                    dataset.tension = 0.4;
                    dataset.pointRadius = 4;
                    dataset.pointHoverRadius = 6;
                }

                datasets.push(dataset);
            });

            return datasets;
        },

        // Configuration pour les graphiques en temps réel
        realTimeConfig: {
            animation: {
                duration: 500,
                easing: 'easeInOutQuart'
            },
            transitions: {
                active: {
                    animation: {
                        duration: 300
                    }
                }
            }
        },

        // Configuration pour l'export des graphiques
        exportConfig: {
            backgroundColor: '#ffffff',
            width: 800,
            height: 600,
            quality: 0.9
        }
    }
};

// Plugin personnalisé pour les animations avancées
export const CustomAnimationPlugin = {
    id: 'customAnimation',
    afterUpdate: function(chart) {
        if (chart.config.options.customAnimation) {
            // Ajouter des animations personnalisées ici
            chart.data.datasets.forEach((dataset, datasetIndex) => {
                dataset.data.forEach((value, index) => {
                    // Animation personnalisée pour chaque point de données
                });
            });
        }
    }
};

// Plugin pour les métriques en temps réel
export const RealTimeMetricsPlugin = {
    id: 'realTimeMetrics',
    afterDraw: function(chart) {
        if (chart.config.options.showRealTimeIndicator) {
            const ctx = chart.ctx;
            const width = chart.width;
            const height = chart.height;
            
            // Dessiner l'indicateur temps réel
            ctx.save();
            ctx.fillStyle = 'rgba(40, 167, 69, 0.8)';
            ctx.beginPath();
            ctx.arc(width - 20, 20, 5, 0, 2 * Math.PI);
            ctx.fill();
            
            ctx.fillStyle = '#333';
            ctx.font = '12px Arial';
            ctx.fillText('LIVE', width - 45, 25);
            ctx.restore();
        }
    }
};

// Configuration d'accessibilité
export const AccessibilityConfig = {
    // Configuration pour les lecteurs d'écran
    screenReader: {
        enabled: true,
        announceDataChanges: true,
        dataTable: true
    },
    
    // Configuration pour les couleurs (contraste élevé)
    highContrast: {
        enabled: false,
        colors: {
            primary: '#000080',
            success: '#006400',
            warning: '#FF8C00',
            danger: '#8B0000',
            info: '#008B8B'
        }
    },
    
    // Configuration pour les animations réduites
    reducedMotion: {
        enabled: false,
        animationDuration: 0
    }
};