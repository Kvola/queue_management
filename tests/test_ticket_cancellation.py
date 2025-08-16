class TestTicketCancellation(models.TransientModel):
    _name = 'test.ticket.cancellation'
    _description = 'Tests d\'annulation de tickets'
    
    def test_normal_cancellation(self):
        """Test d'annulation normale"""
        # Créer un service de test
        service = self.env['queue.service'].create({
            'name': 'Service Test',
            'is_open': True
        })
        
        # Créer un ticket
        ticket = self.env['queue.ticket'].create({
            'service_id': service.id,
            'customer_email': 'test@example.com'
        })
        
        # Tenter l'annulation
        result = ticket.action_cancel_ticket_v2(
            reason='Test annulation',
            cancellation_type='client'
        )
        
        # Vérifications
        assert result['success'], f"Annulation échouée: {result.get('error')}"
        assert ticket.state == 'cancelled'
        assert ticket.cancellation_reason == 'Test annulation'
        
        return True
    
    def test_double_cancellation_prevention(self):
        """Test de prévention double annulation"""
        service = self.env['queue.service'].create({
            'name': 'Service Test',
            'is_open': True
        })
        
        ticket = self.env['queue.ticket'].create({
            'service_id': service.id
        })
        
        # Première annulation
        result1 = ticket.action_cancel_ticket_v2(reason='Premier test')
        assert result1['success']
        
        # Tentative de seconde annulation
        result2 = ticket.action_cancel_ticket_v2(reason='Second test')
        assert not result2['success']
        assert 'déjà annulé' in result2['error'].lower()
        
        return True
    
    def test_cancellation_after_service_started(self):
        """Test annulation après début de service"""
        service = self.env['queue.service'].create({
            'name': 'Service Test',
            'is_open': True
        })
        
        ticket = self.env['queue.ticket'].create({
            'service_id': service.id
        })
        
        # Commencer le service
        ticket.write({'state': 'serving'})
        
        # Tenter l'annulation
        result = ticket.action_cancel_ticket_v2(reason='Test après service')
        assert not result['success']
        
        return True
    
    def run_all_tests(self):
        """Exécuter tous les tests"""
        tests = [
            self.test_normal_cancellation,
            self.test_double_cancellation_prevention,
            self.test_cancellation_after_service_started
        ]
        
        results = {}
        for test in tests:
            try:
                result = test()
                results[test.__name__] = {'success': result, 'error': None}
            except Exception as e:
                results[test.__name__] = {'success': False, 'error': str(e)}
        
        return results
