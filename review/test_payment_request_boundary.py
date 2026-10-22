"""Exercise the actual controller method with a strict fake service client."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from test_integration_contracts import install_frappe_stub
import frappe
from erpnext.pramaan import PramaanError

source=Path(__file__).resolve().parents[1]/'erpnext/accounts/doctype/payment_request/payment_request.py'
controller=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='PaymentRequest')
method=next(n for n in controller.body if isinstance(n,ast.FunctionDef) and n.name=='_create_payment_link')


class PaymentRequestBoundaryTests(unittest.TestCase):
    def invoke(self, client):
        namespace={'get_client':lambda:client,'frappe':frappe}
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),namespace)
        doc=SimpleNamespace(name='PR-WALK',grand_total=10,currency='GBP',subject='Invoice walk',
                            party_name='Walk Customer',email_to='',phone_number='+440000000000',payment_channel='Email')
        namespace['_create_payment_link'](doc)
        return doc

    def test_link_without_email_omits_optional_identity_and_gateway_notifications(self):
        calls=[]
        class FakeClient:
            def call(self,cap,body,**options):
                calls.append((cap,body,options))
                if any(k in body for k in ('notifyEmail','notifySms')) or 'customer' in body:
                    raise AssertionError('The template owns notifications; no incomplete customer profile')
                return {'paymentLinkId':'owned-link','paymentUrl':'https://pramaan.test/connect/link'}
        doc=self.invoke(FakeClient())
        self.assertEqual(doc.payment_link_ref,'owned-link')
        self.assertEqual(calls[0][1]['taxCategory'],'digital_products')
        self.assertTrue(calls[0][2]['idempotency_key'])

    def test_failure_stops_submission_instead_of_returning_a_request_without_link(self):
        class FakeClient:
            def call(self,*args,**options):raise PramaanError('request_rejected')
        with patch.object(frappe,'throw',side_effect=ValueError('Submission stopped'),create=True):
            with self.assertRaisesRegex(ValueError,'Submission stopped'):
                self.invoke(FakeClient())
