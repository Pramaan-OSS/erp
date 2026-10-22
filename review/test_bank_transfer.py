"""Transfer lifecycle through the real client with an in-memory fake transport."""
import copy
import unittest
from test_integration_contracts import install_frappe_stub
from erpnext.pramaan import PramaanClient, PramaanError
from erpnext.erp_integrations.pramaan.transfers import Transfer, request_body


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.status = 'awaiting_payment'
        self.connected = True
        self.saved = []
        self.state = {}
        self.body = request_body('10.75', 'GBP', 'Invoice fixture')
        def transport(method, url, headers, body):
            self.calls.append((url, headers, body))
            if 'Pramaan-Approved-By' in headers: return 403, {'error': {'code':'forbidden'}}
            if url.endswith('/estimate'):
                return 200, {'can_run': self.connected, 'reason': 'connection_required' if not self.connected else None}
            if url.endswith('.create'):
                return 200, {'ref': 'private-handle', 'status': 'awaiting_payment', 'amount': 1075, 'currency': 'GBP', 'reference': 'QUOTE-THIS', 'bank': {'sortCode': '000000', 'accountNumber': '00000000'}}
            if url.endswith('.cancel'):
                self.status = 'cancelled'
            if url.endswith('.list'):
                return 200, {'results': [{'ref': 'rh_list-row', 'createdRef': 'private-handle', 'status': self.status}, {'ref': 'another-invoice', 'status': 'paid'}]}
            return 200, {'status': self.status, 'amount': 1075, 'currency': 'GBP', 'amountReceived': 1075 if self.status == 'paid' else 0}
        self.client = PramaanClient(api_key='fixture-only', transport=transport)
        self.flow = Transfer(self.client, self.state, lambda state, durable: self.saved.append((copy.deepcopy(state), durable)))

    def create(self):
        before = len(self.calls)
        estimate = self.flow.prepare(self.body)
        self.assertEqual(len(self.calls), before + 1)
        return self.flow.confirm(estimate['confirmation'], self.body, 'fixture-user')

    def test_create_awaiting_paid_cancel_and_list(self):
        result = self.create()
        self.assertEqual(result['status'], 'awaiting_payment')
        self.assertEqual(result['reference'], 'QUOTE-THIS')
        self.assertEqual(result['bank']['sortCode'], '000000')
        self.assertNotIn('ref', result)
        self.assertTrue(self.saved[0][1])
        self.assertTrue(self.calls[1][1]['Idempotency-Key'])
        self.assertNotIn('Pramaan-Approved-By', self.calls[1][1])
        self.assertEqual(len(self.flow.listed()), 1)
        self.status = 'partially_paid'
        self.assertEqual(self.flow.refresh(self.body)['status'], 'partially_paid')
        self.status = 'paid'
        self.assertEqual(self.flow.refresh(self.body)['status'], 'paid')
        self.status = 'awaiting_payment'
        estimate = self.flow.prepare(self.body, 'cancel')
        self.assertEqual(self.flow.confirm(estimate['confirmation'], self.body, 'fixture-user')['status'], 'cancelled')

    def test_not_connected_never_creates(self):
        self.connected = False
        with self.assertRaisesRegex(PramaanError, 'Connect your payments account'):
            self.flow.prepare(self.body)
        self.assertEqual(len(self.calls), 1)

    def test_no_confirmation_no_action(self):
        with self.assertRaises(PramaanError):
            self.flow.confirm('', self.body, 'fixture-user')
        self.assertFalse(self.calls)

    def test_changed_amount_requires_new_approval(self):
        estimate = self.flow.prepare(self.body)
        with self.assertRaises(PramaanError):
            self.flow.confirm(estimate['confirmation'], {**self.body, 'amount': 9999}, 'fixture-user')
        self.assertEqual(len(self.calls), 1)

    def test_retry_preserves_key_and_reuses_created_request(self):
        self.flow.prepare(self.body)
        key = self.state['intent']['key']
        self.flow.prepare(self.body)
        self.assertEqual(self.state['intent']['key'], key)
        self.create()
        self.flow.prepare(self.body)
        self.assertEqual(sum(url.endswith('.create') for url, _, _ in self.calls), 1)

    def test_cannot_run_actions_without_key(self):
        for action in ('create', 'cancel'):
            with self.assertRaises(PramaanError):
                self.client.call('payments.transfer-request.' + action, {})

    def test_currency_units_and_receiving_country(self):
        self.assertEqual(request_body('10.005', 'GBP', 'fixture')['amount'], 1001)
        self.assertEqual(request_body('10', 'JPY', 'fixture')['amount'], 10)
        with self.assertRaises(PramaanError):
            request_body(10, 'EUR', 'fixture')
        self.assertEqual(request_body(10, 'EUR', 'fixture', 'nl')['bankCountry'], 'NL')

    def test_no_saved_handle_lists_nothing_without_reading_other_bills(self):
        self.assertEqual(self.flow.listed(), [])
        self.assertFalse(self.calls)

    def test_expired_confirmation_cannot_create(self):
        estimate = self.flow.prepare(self.body)
        self.state['intent']['expires'] = 0
        with self.assertRaises(PramaanError):
            self.flow.confirm(estimate['confirmation'], self.body, 'fixture-user')
        self.assertEqual(len(self.calls), 1)

    def test_paid_reply_with_wrong_amount_is_rejected(self):
        self.create()
        from unittest.mock import patch
        with patch.object(self.client, 'call', return_value={'status':'paid','amount':999,'currency':'GBP','amountReceived':999}):
            with self.assertRaises(PramaanError): self.flow.refresh(self.body)
        self.assertEqual(self.state['result']['status'], 'awaiting_payment')

    def test_lost_action_reply_reuses_original_key(self):
        from unittest.mock import patch
        estimate = self.flow.prepare(self.body)
        original_key = self.state['intent']['key']
        with patch.object(self.client, 'call', side_effect=PramaanError('unavailable', uncertain=True)):
            with self.assertRaises(PramaanError):
                self.flow.confirm(estimate['confirmation'], self.body, 'fixture-user')
        self.assertTrue(self.saved[-1][0]['intent']['sent'])
        with self.assertRaises(PramaanError):
            self.flow.prepare({**self.body, 'amount':2000})
        estimate = self.flow.prepare(self.body)
        self.flow.confirm(estimate['confirmation'], self.body, 'fixture-user')
        create_calls = [options for url, options, _ in self.calls if url.endswith('.create')]
        self.assertEqual(create_calls[0]['Idempotency-Key'], original_key)
