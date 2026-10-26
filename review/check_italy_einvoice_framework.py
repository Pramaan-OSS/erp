"""Durable submission checks against the real framework and a disposable database."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

if os.environ.get('PRAMAAN_FAKE') != '1' or os.environ.get('PRAMAAN_API_KEY'):
    raise SystemExit('Use fake transport and an empty key.')
root = Path(os.environ.get('ERP_APP_ROOT', '/app'))
sys.path.insert(0, str(root / 'review'))
os.chdir(root / '.runtime/bench/sites')
import frappe
from italy_fixture import seed
from erpnext.erp_integrations.pramaan import italy_einvoice as api
from erpnext.pramaan import PramaanClient

frappe.init(site=os.environ['ERP_SITE_NAME']); frappe.connect(); frappe.set_user('Administrator')


class DurableInvoiceTests(unittest.TestCase):
    def setUp(self):
        self.name, self.company = seed()
        self.calls = []
        self.mode = 'pending'
        def transport(method, url, headers, body):
            self.calls.append((url, headers, body))
            with patch.dict(os.environ, {'PRAMAAN_FAKE_EINVOICE': self.mode}):
                return PramaanClient._fake(method, url, headers, body)
        self.client = PramaanClient(api_key='fixture', transport=transport)
        self.boundary = patch.object(api, 'get_client', return_value=self.client)
        self.boundary.start()

    def tearDown(self):
        self.boundary.stop(); frappe.set_user('Administrator'); frappe.db.rollback()

    def prepare(self):
        return api.action(self.name, 'prepare')['confirmation']

    def send(self):
        return api.action(self.name, 'confirm', self.prepare())

    def submits(self):
        return [x for x in self.calls if x[0].endswith('/edi.einvoice.submit')]

    def test_pending_acceptance_receipt_and_original_account(self):
        self.assertEqual(self.send()['state'], 'Pending')
        self.assertEqual(api.action(self.name, 'confirm', 'duplicate')['state'], 'Pending')
        api.configure(self.company, 'conn_Other')
        self.mode = 'accepted'
        self.assertEqual(api.action(self.name, 'refresh')['receipt'], 'delivered')
        self.assertEqual(self.calls[-1][1]['Pramaan-Account'], 'conn_Example')
        self.assertEqual(len(self.submits()), 1)
        with self.assertRaises(frappe.ValidationError):
            api.protect_xml(self.name)

    def test_uncertain_survives_rollback_and_account_change(self):
        token = self.prepare(); self.mode = 'uncertain'
        self.assertEqual(api.action(self.name, 'confirm', token)['state'], 'Uncertain')
        frappe.db.rollback()
        api.configure(self.company, 'conn_Other')
        self.assertEqual(api.action(self.name, 'prepare')['state'], 'Uncertain')
        self.assertEqual(api.action(self.name, 'refresh')['state'], 'Uncertain')
        self.assertEqual(len(self.submits()), 1)
        self.assertTrue(api._active(self.name).reservation)

    def test_safe_refusal_frees_number_and_requires_new_confirmation(self):
        token = self.prepare(); self.mode = 'refused'
        self.assertEqual(api.action(self.name, 'confirm', token)['state'], 'Refused')
        self.assertFalse(frappe.db.get_value(api.DOCTYPE, {'invoice': self.name}, 'reservation'))
        self.mode = 'pending'
        with self.assertRaises(frappe.ValidationError):
            api.action(self.name, 'confirm', token)
        self.assertEqual(self.send()['state'], 'Pending')
        self.assertEqual(len(self.submits()), 2)
        self.assertNotEqual(self.submits()[0][1]['Idempotency-Key'], self.submits()[1][1]['Idempotency-Key'])

    def test_stale_document_and_account_confirmation(self):
        token = self.prepare()
        api.configure(self.company, 'conn_Other')
        with self.assertRaises(frappe.ValidationError):
            api.action(self.name, 'confirm', token)
        self.assertFalse(self.submits())
        token = self.prepare()
        frappe.db.set_value('Sales Invoice', self.name, 'remarks', 'Changed after preview')
        frappe.db.commit()
        with self.assertRaises(frappe.ValidationError):
            api.action(self.name, 'confirm', token)
        self.assertFalse(self.submits())

    def test_unavailable_read_preserves_state_and_distinct_receipt(self):
        self.send(); self.mode = 'delivery_unavailable'
        self.assertEqual(api.action(self.name, 'refresh')['receipt'], 'delivery_unavailable')
        self.mode = 'unavailable'
        result = api.action(self.name, 'refresh')
        self.assertEqual(result['state'], 'Accepted')
        self.assertEqual(result['receipt'], 'delivery_unavailable')
        self.assertIn('error', result)

    def test_rejected_submission_never_resubmits(self):
        self.send(); self.mode = 'rejected'
        self.assertEqual(api.action(self.name, 'refresh')['state'], 'Rejected')
        self.assertEqual(api.action(self.name, 'prepare')['state'], 'Rejected')
        self.assertEqual(len(self.submits()), 1)

    def test_permissions_precede_service_and_account_configuration(self):
        with patch.object(frappe, 'get_roles', return_value=[]):
            with self.assertRaises(frappe.PermissionError):
                api.configure(self.company, 'conn_Other')
        with patch.object(frappe, 'get_doc', side_effect=frappe.PermissionError):
            for operation in ['status', 'refresh', 'prepare', 'confirm']:
                with self.assertRaises(frappe.PermissionError):
                    api.action(self.name, operation)
        self.assertFalse(self.calls)

    def test_guest_and_restricted_user_cannot_read_or_send(self):
        user = 'italy-viewer@fixture.test'
        if not frappe.db.exists('User', user):
            frappe.get_doc({'doctype': 'User', 'email': user, 'first_name': 'Invoice Viewer', 'send_welcome_email': 0, 'user_type': 'Website User'}).insert(ignore_permissions=True)
            frappe.db.commit()
        for name in ['Guest', user]:
            frappe.set_user(name)
            for operation in ['status', 'refresh', 'prepare', 'confirm']:
                with self.assertRaises(frappe.PermissionError):
                    api.action(self.name, operation)
        self.assertFalse(self.calls)
        frappe.set_user('Administrator')

    def test_connection_and_attached_xml_cannot_be_overwritten(self):
        company = frappe.get_doc('Company', self.company)
        company.italy_invoicing_connection = 'conn_Injected'
        api.protect_connection(company)
        self.assertEqual(company.italy_invoicing_connection, 'conn_Example')
        self.send()
        file = frappe.get_doc('File', {'attached_to_doctype': 'Sales Invoice', 'attached_to_name': self.name})
        with self.assertRaises(frappe.ValidationError):
            frappe.delete_doc('File', file.name)

    def test_unique_number_and_frozen_payload(self):
        self.send()
        record = api._active(self.name)
        snapshot = json.loads(record.payload)
        body = snapshot['request']
        self.assertEqual(snapshot['xmlDigest'], api.digest(body['xml']))
        self.assertEqual(body['lines'][0]['quantity'], 2)
        self.assertEqual(body['taxes'], [{'rate': 22, 'amount': 5.43}])
        copy = frappe.copy_doc(record); copy.name = None
        with self.assertRaises(frappe.UniqueValidationError):
            copy.insert(ignore_permissions=True)

    def test_concurrent_confirmations_dispatch_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        token = self.prepare()
        barrier = Barrier(2)
        def send():
            frappe.init(site=os.environ['ERP_SITE_NAME']); frappe.connect(); frappe.set_user('Administrator')
            try:
                barrier.wait(timeout=10)
                return api.action(self.name, 'confirm', token)['state']
            finally:
                frappe.db.rollback(); frappe.destroy()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: send(), range(2)))
        self.assertEqual(results, ['Pending', 'Pending'])
        self.assertEqual(len(self.submits()), 1)

    def test_no_effect_server_refusal_releases_number(self):
        token = self.prepare()
        with patch.object(self.client, '_transport', return_value=(503, {'error': {'code': 'upstream_unavailable', 'effect': 'none'}})):
            self.assertEqual(api.action(self.name, 'confirm', token)['state'], 'Refused')
        self.assertFalse(frappe.db.get_value(api.DOCTYPE, {'invoice': self.name}, 'reservation'))

    def test_malformed_submit_keeps_known_reference_for_reads(self):
        token = self.prepare()
        with patch.object(self.client, 'run', return_value={'ref': 'fixture-known', 'status': 'unknown'}):
            self.assertEqual(api.action(self.name, 'confirm', token)['state'], 'Uncertain')
        frappe.db.rollback()
        self.assertEqual(api._active(self.name).result_ref, 'fixture-known')
        self.mode = 'accepted'
        self.assertEqual(api.action(self.name, 'refresh')['state'], 'Accepted')
        self.assertEqual(self.calls[-1][2], {'ref': 'fixture-known'})

    def test_crash_intent_blocks_following_request(self):
        token = self.prepare()
        with patch.object(self.client, 'run', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):
                api.action(self.name, 'confirm', token)
        frappe.db.rollback()
        self.assertEqual(api.action(self.name, 'prepare')['state'], 'Sending')
        self.assertFalse(self.submits())

try:
    with patch.object(PramaanClient, '_http', side_effect=AssertionError('Live calls forbidden')):
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DurableInvoiceTests))
finally:
    frappe.db.rollback(); frappe.destroy()
raise SystemExit(not result.wasSuccessful())
