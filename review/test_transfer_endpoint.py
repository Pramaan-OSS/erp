"""Permission and settlement checks for the actual endpoint with local document doubles."""
import importlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_integration_contracts import install_frappe_stub
import frappe
import test_bank_transfer


class EndpointTests(unittest.TestCase):
    setUp = test_bank_transfer.TransferTests.setUp
    def invoke(self, **kwargs):
        with patch.object(frappe, 'whitelist', lambda **kw: lambda fn: fn, create=True):
            endpoint = importlib.import_module('erpnext.erp_integrations.pramaan.bank_transfer')
        self.doc = getattr(self, 'doc', SimpleNamespace(name='fixture', grand_total=10.75, currency='GBP',
            docstatus=1, payment_request_type='Inward', status='Requested', bank_transfer_data='{}',
            check_permission=Mock(), reload=Mock(), set_as_paid=Mock()))
        def save(field, value):
            setattr(self.doc, field, value)
        self.doc.db_set = save
        db = SimpleNamespace(sql=Mock(), commit=Mock())
        def fail(message, *args):
            raise ValueError(message)
        with patch.object(frappe, 'session', SimpleNamespace(user='fixture-user'), create=True), patch.object(frappe, 'db', db, create=True), patch.object(frappe, 'get_doc', return_value=self.doc, create=True), patch.object(frappe, 'throw', fail, create=True), patch.object(endpoint, 'get_client', return_value=self.client):
            return endpoint.transfer('fixture', **kwargs)

    def test_endpoint_settles_only_after_get_reports_paid(self):
        estimate = self.invoke(operation='create')
        self.invoke(operation='confirm', confirmation=estimate['confirmation'])
        self.doc.set_as_paid.assert_not_called()
        self.status = 'paid'
        self.invoke(operation='status')
        self.doc.set_as_paid.assert_called_once()
        self.doc.check_permission.assert_called_with('write')

    def test_permission_denied_never_calls_service(self):
        self.invoke(operation='status')
        self.doc.check_permission.side_effect = ValueError('Not permitted')
        with self.assertRaisesRegex(ValueError, 'Not permitted'):
            self.invoke(operation='create')
        self.assertFalse(self.calls)

    def test_new_eur_status_does_not_require_country(self):
        self.invoke(operation='status')
        self.doc.currency = 'EUR'
        self.assertEqual(self.invoke(operation='status')['status'], 'not_created')
