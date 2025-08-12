odoo.define('queue_management.website', function (require) {
    'use strict';

    var core = require('web.core');
    var ajax = require('web.ajax');
    
    var QueueManager = {
        init: function() {
            this.bindEvents();
            this.startAutoRefresh();
        },

        bindEvents: function() {
            var self = this;
            
            // Formulaire de prise de ticket
            $('#ticket-form').on('submit', function(e) {
                e.preventDefault();
                self.takeTicket();
            });
        },

        takeTicket: function() {
            var self = this;
            var serviceId = $('button[data-service-id]').data('service-id');
            var formData = {
                service_id: serviceId,
                customer_phone: $('#customer_phone').val(),
                customer_email: $('#customer_email').val(),
                customer_name: $('#customer_name').val()
            };

            // Désactiver le bouton pendant la requête
            var $submitBtn = $('#ticket-form button[type="submit"]');
            $submitBtn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i> Traitement...');

            ajax.jsonRpc('/queue/take_ticket', 'call', formData).then(function(result) {
                if (result.error) {
                    self.showError(result.error);
                } else {
                    self.showTicketSuccess(result);
                    self.refreshQueueStatus();
                }
            }).catch(function(error) {
                self.showError('Erreur lors de la prise de ticket');
                console.error(error);
            }).finally(function() {
                $submitBtn.prop('disabled', false).html('<i class="fa fa-ticket"></i> Prendre mon Ticket');
            });
        },

        showTicketSuccess: function(result) {
            $('#result-ticket-number').text(result.ticket_number);
            $('#result-position').text(result.position);
            $('#result-wait-time').text(Math.round(result.estimated_wait));
            $('#ticket-result').show();
            $('#ticket-form')[0].reset();
        },

        showError: function(message) {
            var alertHtml = '<div class="alert alert-danger alert-dismissible fade show" role="alert">' +
                           message +
                           '<button type="button" class="close" data-dismiss="alert">' +
                           '<span>&times;</span></button></div>';
            $('#ticket-form').prepend(alertHtml);
        },

        startAutoRefresh: function() {
            var self = this;
            setInterval(function() {
                self.refreshQueueStatus();
            }, 30000); // Refresh toutes les 30 secondes
        },

        refreshQueueStatus: function() {
            var serviceId = $('button[data-service-id]').data('service-id');
            if (!serviceId) return;

            ajax.jsonRpc('/queue/status/' + serviceId, 'call', {}).then(function(result) {
                if (!result.error) {
                    self.updateDisplay(result);
                }
            });
        },

        updateDisplay: function(data) {
            $('#waiting-count').text(data.waiting_count);
            $('#current-ticket').text('#' + data.current_ticket);
            
            // Mettre à jour la liste des tickets
            var $queueList = $('#queue-list');
            if (data.tickets.length > 0) {
                var html = '<div class="list-group">';
                data.tickets.forEach(function(ticket) {
                    html += '<div class="list-group-item d-flex justify-content-between align-items-center">' +
                           '<div><strong>Ticket #' + ticket.number + '</strong></div>' +
                           '<div><span class="badge badge-info">~' + Math.round(ticket.estimated_wait) + ' min</span></div>' +
                           '</div>';
                });
                html += '</div>';
                $queueList.html(html);
            } else {
                $queueList.html('<div class="text-center text-muted py-4">' +
                               '<i class="fa fa-check-circle fa-3x mb-3"></i>' +
                               '<p>Aucun client en attente</p></div>');
            }
        }
    };

    // Initialiser quand la page est prête
    $(document).ready(function() {
        if ($('#ticket-form').length) {
            QueueManager.init();
        }
    });

    return QueueManager;
});