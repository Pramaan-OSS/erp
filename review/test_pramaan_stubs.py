"""Standalone checks: python3 -m unittest discover -s review -p 'test_*.py'."""

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "erpnext" / "pramaan.py"
SPEC = importlib.util.spec_from_file_location("pramaan_stub_boundary", MODULE_PATH)
boundary = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = boundary
SPEC.loader.exec_module(boundary)


class FakeTransport:
    """Strict wire-contract fake; no network and no permissive shortcut."""
    def __init__(self, response=None, status=200):
        self.requests = []
        self.status = status
        self.response = response if response is not None else {}

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url, headers, body))
        return self.status, self.response


class ContractTests(unittest.TestCase):
    def test_known_capabilities_are_declared(self):
        expected = {
            "payments.account.status", "payments.account.connect", "payments.account.session.create",
            "payments.transfer-request.create", "payments.transfer-request.get",
            "payments.transfer-request.list", "payments.transfer-request.cancel",
            "finance.exchange-rate.get", "finance.exchange-rate.history",
            "finance.vat-number.validate", "finance.tax-rates.get", "finance.vat-rates.get",
            "banking.connection.start", "banking.connection.status", "banking.accounts.list",
            "banking.transactions.sync", "banking.transactions.list", "banking.account.balances.get",
            "banking.institutions.search", "routes.compute", "routes.stops.sequence", "sms.send",
            "payments.payment-link.create", "payments.checkout.create", "payments.payment.get",
            "payments.payment-link.orders.list", "email.send", "email.template.send",
            "email.message.send", "email.message.reply", "auth.social.exchange",
            "geo.address.validate", "geo.address.parse", "geo.address.geocode",
            "shipping.label.purchase", "shipping.container.track", "shipping.delivery.estimate",
            "companies.enrich", "companies.domain.find", "companies.tax-identifiers.list",
            "document.extract",
            "india.gst.consent.create", "india.gst.einvoice.create", "india.gst.einvoice.get",
            "india.gst.einvoice.cancel", "india.gst.einvoice.qr.get",
        }
        self.assertEqual(boundary.PramaanClient.CAPABILITIES, expected)
        self.assertTrue(boundary.PramaanClient.ACTIONS <= boundary.PramaanClient.CAPABILITIES)

    def test_approved_outcomes_only(self):
        self.assertEqual(boundary.PramaanClient.OUTCOMES,
                         frozenset({"invoice.process", "tax.quote", "payments.reconcile"}))

    def test_mutating_capabilities_need_idempotency_keys(self):
        read_only = boundary.PramaanClient.CAPABILITIES - boundary.PramaanClient.ACTIONS
        self.assertTrue(read_only)
        for capability in boundary.PramaanClient.ACTIONS:
            client = boundary.PramaanClient(api_key="fake", transport=FakeTransport())
            with self.assertRaises(boundary.PramaanError, msg=capability):
                client.run(capability, {})

    def test_off_features_have_plain_unavailable_reasons(self):
        availability = {item.feature: item for item in boundary.PramaanClient().availability()}
        self.assertTrue(availability["email_sending"].enabled)
        self.assertTrue(availability["social_sign_in"].enabled)
        for feature in ("bank_feeds", "routing", "sms", "payment_links", "addresses",
                        "shipping", "company_data", "tax_data", "document_intake",
                        "currency_rates", "invoice_intake"):
            self.assertFalse(availability[feature].enabled, feature)
            reason = str(availability[feature].reason)
            self.assertIn("not available yet", reason, feature)
            self.assertNotIn("PRAMAAN", reason.upper().replace("Pramaan", "PRAMAAN"))


if __name__ == "__main__":
    unittest.main()
