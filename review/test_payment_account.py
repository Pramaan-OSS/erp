"""Account setup contracts: fake transport only; no credentials reach logs or storage."""
import importlib
import json
import unittest
from contextlib import nullcontext
from pramaan import PramaanError as SDKPramaanError
from pramaan.testing import fake_payments_account
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_integration_contracts import install_frappe_stub
import frappe
from erpnext.pramaan import PramaanClient

with patch.object(frappe, 'whitelist', lambda **kw: lambda fn: fn, create=True):
    account = importlib.import_module('erpnext.erp_integrations.pramaan.payment_account')


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.sdk = fake_payments_account(state="setup_incomplete")
        self.calls = []
        self.result = {'status':'pending','chargesEnabled':False,'payoutsEnabled':False,
                       'requirementsDue':['external_account','company.tax_id','unknown.private-field']}
        self.storage = {}
        cache = SimpleNamespace(set_value=lambda key, value, **kw: self.storage.update({key:value}),
            get_value=self.storage.get, delete_value=lambda key:self.storage.pop(key,None))
        def transport(method,url,headers,body):
            self.calls.append((url,headers,body))
            if url.endswith('/estimate'): return 200, {'can_run':True}
            if url.endswith('.connect'):
                if 'Pramaan-Approved-By' in headers: return 403, {'error': {'code': 'forbidden'}}
                return 200, {'onboardingMode':'embedded'}
            if url.endswith('.session.create'):
                if 'Pramaan-Approved-By' in headers:
                    return 403, {'error': {'code': 'forbidden'}}
                return 200, {'clientSecret':'fixture_secret_only','publishableKey':'pk_test_fixture','accountId':'never-public'}
            return 200, self.result
        self.client = PramaanClient(api_key='fixture-only',transport=transport)
        self.patches = [patch.object(account, 'Pramaan', side_effect=lambda *args, **kw: nullcontext(self.sdk)),
            patch.object(account,'get_client',return_value=self.client),
            patch.object(frappe,'session',SimpleNamespace(user='Administrator'),create=True),
            patch.object(frappe,'PermissionError',ValueError,create=True),
            patch.object(frappe,'only_for',Mock(),create=True), patch.object(frappe,'cache',cache,create=True),
            patch.object(frappe.utils,'get_url',return_value='https://app.example',create=True),
            patch.object(frappe,'log_error',Mock(),create=True)]
        for item in self.patches: item.start(); self.addCleanup(item.stop)

    def test_each_state_and_plain_requirements(self):
        reply = account.status()
        self.assertEqual(reply['state'],'incomplete')
        self.assertEqual(reply['requirements'][0],'Add a bank account for payouts')
        self.assertNotIn('private-field',str(reply))
        self.result.update(status='ready',chargesEnabled=True,payoutsEnabled=False)
        self.assertEqual(account.status()['state'],'incomplete')
        self.result['payoutsEnabled']=True
        self.assertEqual(account.status()['state'],'ready')
        with patch.object(self.client,'_transport',return_value=(409,{'error':{'code':'connection_required'}})):
            self.assertEqual(account.status()['state'],'not_connected')

    def test_role_check_happens_before_every_call(self):
        frappe.only_for.side_effect = ValueError('Not permitted')
        for method in (account.status,account.connect,account.session):
            with self.assertRaises(ValueError): method()
        self.assertFalse(self.calls)
        self.assertFalse(self.sdk.calls)
        frappe.session.user='Guest'; frappe.only_for.side_effect=None
        with self.assertRaises(ValueError): account.session()
        self.assertFalse(self.calls)

    def test_session_is_filtered_uncached_and_uses_fresh_keys(self):
        one=account.session(); two=account.session()
        self.assertEqual(set(one),{'clientSecret','publishableKey'})
        self.assertNotEqual(one['clientSecret'], two['clientSecret'])
        calls = [call for call in self.sdk.calls if call[0] == 'payments.account.session.create']
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0][2].idempotency_key, calls[1][2].idempotency_key)
        self.assertEqual(calls[0][1]['components'], account.COMPONENTS)
        self.assertIsNone(calls[0][2].approved_by)
        account.Pramaan.assert_called_with(self.client._api_key, base_url=self.client._base_url)
        self.assertFalse(self.storage)
        frappe.log_error.assert_not_called()

    def test_session_errors_do_not_expose_secret(self):
        with self.assertLogs(account.__name__, level='WARNING') as logs, \
                patch.object(account,'create_account_session',side_effect=RuntimeError('fixture_secret_only')):
            with self.assertRaises(ValueError) as raised: account.session()
        self.assertNotIn('fixture_secret_only',str(raised.exception))
        self.assertIn('exception_class=RuntimeError pramaan_code=unexpected_error',logs.output[0])
        self.assertNotIn('fixture_secret_only',str(logs.output))
        import traceback
        self.assertNotIn('fixture_secret_only',''.join(traceback.format_exception(raised.exception)))
        frappe.log_error.assert_not_called()

    def test_package_rejection_is_logged_without_upstream_body(self):
        with patch.object(self.sdk, 'run', side_effect=SDKPramaanError('forbidden', 'fixture_secret_only')):
            with self.assertLogs(account.__name__, level='WARNING') as logs:
                with self.assertRaises(ValueError) as raised:
                    account.session()
        self.assertIn('exception_class=PramaanError pramaan_code=unavailable', logs.output[0])
        self.assertNotIn('fixture_secret_only', str(logs.output))
        self.assertNotIn('fixture_secret_only', str(raised.exception))

    def test_package_states_and_disconnected_session(self):
        for state in ('setup_incomplete', 'restricted', 'ready'):
            self.sdk.state = state
            self.assertEqual(set(account.session()), {'clientSecret', 'publishableKey'})
        self.sdk.state = 'not_connected'
        self.sdk.calls.clear()
        with self.assertRaises(ValueError):
            account.session()
        self.assertEqual([call[0] for call in self.sdk.calls], ['payments.account.status'])

    def test_session_rejects_malformed_secret_without_retaining_error(self):
        from traceback import format_exception
        run = self.sdk.run
        def malformed(capability, body, options=None):
            result = run(capability, body, options)
            if capability == 'payments.account.session.create':
                result['clientSecret'] = 'fixture_secret_only<script>'
            return result
        with patch.object(self.sdk, 'run', side_effect=malformed):
            with self.assertRaises(ValueError) as raised:
                account.session()
        self.assertNotIn('fixture_secret_only', ''.join(format_exception(raised.exception)))
        self.assertFalse(self.storage)

    def test_missing_key_stops_before_package_construction(self):
        self.client._api_key = ''
        with self.assertRaises(ValueError):
            account.session()
        account.Pramaan.assert_not_called()
        self.assertFalse(self.sdk.calls)

    def test_connect_estimate_then_approval(self):
        estimate=account.connect(country='GB')
        self.assertTrue(self.calls[0][0].endswith('/estimate'))
        self.assertEqual(len(self.calls),1)
        with self.assertRaises(ValueError): account.connect(confirmation=estimate['confirmation'],country='US')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(account.connect(confirmation=estimate['confirmation'],country='GB'),{'mode':'embedded'})
        self.assertTrue(self.calls[-1][1]['Idempotency-Key'])
        self.assertNotIn('Pramaan-Approved-By',self.calls[-1][1])
        self.assertEqual(self.calls[-1][2]['returnUrl'],'https://app.example/app/payments-account')

    def test_no_store_link_and_runtime_policy(self):
        class Response:
            status_code=417
            is_json=True
            headers={'Content-Security-Policy':"script-src 'self'; frame-src 'self'; img-src 'self'"}
            def get_json(self,**kwargs): return {'_server_messages':json.dumps([json.dumps({'message':'Connect your payments account first, then try again.'})])}
            def set_data(self,value): self.body=value
        response=Response()
        with patch.object(frappe,'request',SimpleNamespace(path='/api/method/'+account.__name__+'.session'),create=True):
            account.browser_response(response)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        with patch.object(frappe,'request',SimpleNamespace(path='/api/v1/method/'+account.__name__+'.session'),create=True):
            response.headers.pop('Cache-Control'); account.browser_response(response)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertIn('/app/payments-account',response.body)
        self.assertIn('https://connect-js.stripe.com',response.headers['Content-Security-Policy'])
        self.assertNotIn('connect-src *',response.headers['Content-Security-Policy'])
