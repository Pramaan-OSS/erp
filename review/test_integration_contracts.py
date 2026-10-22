"""Contract checks for the app's integration modules; no framework, no network."""
import importlib
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# intelligence.py reads permission-checked files through frappe; the contract
# under test is the pure mapping, so a minimal stub satisfies the import.
def install_frappe_stub():
    utils = types.ModuleType("frappe.utils")
    utils.cstr = str
    stub = types.ModuleType("frappe")
    stub._ = lambda text: text
    stub.throw = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError(args[0]))
    stub.utils = utils
    sys.modules["frappe"] = stub
    sys.modules["frappe.utils"] = utils
    return stub


if "frappe" not in sys.modules:
    install_frappe_stub()

sys.path.insert(0, str(ROOT))


class ExchangeTests(unittest.TestCase):
    def test_latest_and_dated_requests(self):
        from erpnext.erp_integrations.pramaan import exchange

        self.assertEqual(exchange.latest_rate_request("usd ", "eur"), {"from": "USD", "to": "EUR"})
        dated = exchange.dated_rate_request("USD", "EUR", "2026-02-03 00:00:00")
        self.assertEqual(dated, {"from": "USD", "to": "EUR", "startDate": "2026-02-03", "endDate": "2026-02-03"})

    def test_rate_from_latest_prefers_rate_then_inverse(self):
        from erpnext.erp_integrations.pramaan import exchange

        self.assertEqual(exchange.rate_from_latest({"rate": 2.0, "inverseRate": 0.5}), 2.0)
        self.assertAlmostEqual(exchange.rate_from_latest({"inverseRate": 0.25}), 4.0)
        with self.assertRaises(ValueError):
            exchange.rate_from_latest({})

    def test_rate_from_history_picks_day_then_latest(self):
        from erpnext.erp_integrations.pramaan import exchange

        result = {"rates": [{"date": "2026-02-02", "rate": 1.5}, {"date": "2026-02-03", "rate": 1.7}]}
        self.assertEqual(exchange.rate_from_history(result, "2026-02-03"), 1.7)
        self.assertEqual(exchange.rate_from_history(result, "2026-02-09"), 1.7)
        with self.assertRaises(ValueError):
            exchange.rate_from_history({"rates": []}, "2026-02-03")


class BankingTests(unittest.TestCase):
    def test_connection_start_request_binds_country_and_return(self):
        from erpnext.erp_integrations.pramaan import banking

        body = banking.connection_start_request("de", "person-1", "https://app.example/return")
        self.assertEqual(body, {"country": "DE", "endUserRef": "person-1", "returnUrl": "https://app.example/return"})
        with_ref = banking.connection_start_request("de", "person-1", "https://app.example/return", "inst-1")
        self.assertEqual(with_ref["institutionRef"], "inst-1")

    def test_bank_picker_uses_catalogue_institutions_and_row_handles(self):
        from erpnext.erp_integrations.pramaan import banking
        from test_pramaan_stubs import boundary, FakeTransport
        fake = FakeTransport({"institutions": [
            {"rowRef": "owned-bank", "name": "Test Bank", "countries": ["GB"]},
            {"name": "No owned handle", "countries": ["GB"]}]})
        client = boundary.PramaanClient(api_key="fake", transport=fake)
        body = banking.institution_search_request("gb", "  ")
        self.assertEqual(body, {"country": "GB"})
        self.assertEqual(banking.institution_search_request("gb", " Bank "), {"country": "GB", "query": "Bank"})
        rows = banking.institution_rows(client.call("banking.institutions.search", body))
        self.assertEqual(rows, [{"ref": "owned-bank", "name": "Test Bank"}])

    def test_sync_request_bounds_limit_and_keeps_cursor(self):
        from erpnext.erp_integrations.pramaan import banking

        self.assertEqual(banking.transactions_sync_request("ref"), {"ref": "ref", "limit": 100})
        self.assertEqual(banking.transactions_sync_request("ref", "cur", 500), {"ref": "ref", "limit": 100, "cursor": "cur"})

    def test_minor_units_and_transaction_rows(self):
        from erpnext.erp_integrations.pramaan import banking

        self.assertAlmostEqual(banking.minor_to_amount(-1234, "GBP"), -12.34)
        self.assertAlmostEqual(banking.minor_to_amount(100, "KWD"), 0.100)
        row = banking.transaction_row("acct-1", {
            "rowRef": "tx-1", "amount": -5000, "currency": "USD",
            "date": "2026-02-03", "description": "Coffee", "counterparty": {"name": "Cafe"},
        })
        self.assertEqual(row["withdrawal"], 50.0)
        self.assertEqual(row["deposit"], 0.0)
        self.assertEqual(row["transaction_id"], "tx-1")
        self.assertIsNone(banking.transaction_row("acct-1", {"amount": None}))


class RoutingTests(unittest.TestCase):
    def test_compute_request_shapes_legs_and_optimization(self):
        from erpnext.erp_integrations.pramaan import routing

        body = routing.compute_request(["Origin", " A ", "Dest"], optimize=True)
        self.assertEqual(body["origin"], {"address": "Origin"})
        self.assertEqual(body["destination"], {"address": "Dest"})
        self.assertEqual(body["waypoints"], [{"address": "A"}])
        self.assertTrue(body["optimizeWaypointOrder"])
        self.assertTrue(body["legs"])
        with self.assertRaises(ValueError):
            routing.compute_request(["Only"], optimize=False)

    def test_route_summary_normalizes_legs(self):
        from erpnext.erp_integrations.pramaan import routing

        summary = routing.route_summary({"routes": [{
            "distanceMeters": 300,
            "waypointOrder": [1, 0],
            "legs": [
                {"distanceMeters": 100, "durationSeconds": 60, "end": {"latitude": 1.0, "longitude": 2.0}},
                {"distanceMeters": 200, "durationSeconds": 120, "end": {"latitude": 3.0, "longitude": 4.0}},
            ],
        }]})
        self.assertEqual(summary["waypoint_order"], [1, 0])
        self.assertEqual(summary["legs"][0]["lat"], 1.0)
        self.assertEqual(summary["total_distance_meters"], 300)
        self.assertFalse(routing.route_summary({"routes": []}))


class SmsTests(unittest.TestCase):
    def test_normalize_receiver(self):
        from erpnext.erp_integrations.pramaan import sms

        self.assertEqual(sms.normalize_receiver("+1 (555) 000-1111"), "+15550001111")
        self.assertEqual(sms.normalize_receiver("4915112345678"), "+4915112345678")
        with self.assertRaises(ValueError):
            sms.normalize_receiver("  ")

    def test_send_request_truncates_body(self):
        from erpnext.erp_integrations.pramaan import sms

        request = sms.send_request("+15550001111", "x" * 2000)
        self.assertEqual(len(request["body"]), sms.MAX_BODY)


class PaymentsTests(unittest.TestCase):
    def test_minor_units(self):
        from erpnext.erp_integrations.pramaan import payments

        self.assertEqual(payments.to_minor_units(12.34, "USD"), 1234)
        self.assertEqual(payments.to_minor_units(0.1, "KWD"), 100)
        with self.assertRaises(ValueError):
            payments.to_minor_units(100_000_000, "USD")

    def test_payment_link_request_fields(self):
        from erpnext.erp_integrations.pramaan import payments

        body = payments.payment_link_request(
            100.0, "inr", description="Invoice INV-1", reference="PRQ-1",
            customer_email="person@example.com", notify_email=True,
        )
        self.assertEqual(body["amount"], 10000)
        self.assertEqual(body["taxCategory"], "digital_products")
        self.assertEqual(body["currency"], "INR")
        self.assertEqual(body["customer"]["email"], "person@example.com")
        self.assertTrue(body["notifyEmail"])
        self.assertNotIn("notifySms", body)

    def test_payment_link_tax_category_uses_the_one_setting(self):
        from unittest.mock import patch
        from erpnext.erp_integrations.pramaan import payments
        with patch.dict("os.environ", {"PRAMAAN_TAX_CATEGORY": "services"}):
            self.assertEqual(payments.payment_link_request(1, "GBP")["taxCategory"], "services")

    def test_link_result_and_paid_orders(self):
        from erpnext.erp_integrations.pramaan import payments

        link = payments.link_from_result({"paymentLinkId": "l1", "paymentUrl": "https://pay.example/l1"})
        self.assertEqual(link["payment_link_ref"], "l1")
        with self.assertRaises(ValueError):
            payments.link_from_result({"paymentLinkId": "l1"})
        total = payments.paid_order_amount({"items": [
            {"orderId": "o1", "status": "paid", "amount": 500},
            {"orderId": "o2", "status": "active", "amount": 700},
        ]})
        self.assertEqual(total, 500)


class IntelligenceTests(unittest.TestCase):
    def test_domain_from_website(self):
        from erpnext.erp_integrations.pramaan import intelligence

        self.assertEqual(intelligence.domain_from_website("https://www.example.com/path"), "example.com")
        self.assertEqual(intelligence.domain_from_website("example.com"), "example.com")
        self.assertEqual(intelligence.domain_from_website(""), "")

    def test_company_prefill_request_needs_something(self):
        from erpnext.erp_integrations.pramaan import intelligence

        self.assertEqual(intelligence.company_prefill_request(name="Acme"), {"name": "Acme"})
        with self.assertRaises(ValueError):
            intelligence.company_prefill_request()

    def test_shipping_uses_country_and_postal_code_contract(self):
        from erpnext.erp_integrations.pramaan import intelligence
        body = intelligence.delivery_estimate_request(
            {"countryCode": "gb", "postalCode": "SW1A 2AA"},
            {"country": "GB", "postalCode": "SW1A 1AA"}, "standard", "2026-10-18")
        self.assertEqual(body["origin"], {"country": "GB", "postalCode": "SW1A 2AA"})
        self.assertEqual(body["destination"]["country"], "GB")
        with self.assertRaises(ValueError):
            intelligence.delivery_estimate_request({"country": "United Kingdom"}, {}, "standard")

    def test_company_location_from_live_reply_is_readable(self):
        from erpnext.erp_integrations.pramaan import intelligence
        fields = intelligence.company_prefill({"location": {
            "city": "San Francisco", "region": "California", "country": "United States"}})
        self.assertEqual(fields["location"], "San Francisco, California, United States")

    def test_document_result_unwraps_live_data(self):
        from erpnext.erp_integrations.pramaan import intelligence
        fields = intelligence.invoice_lines_result({"data": {
            "supplierName": "Walk Supplies", "invoiceNumber": "INV-1", "currency": "GBP",
            "lines": [{"description": "Consulting", "quantity": 2, "unitPrice": 10}]}, "truncated": False})
        self.assertEqual(fields["invoice_number"], "INV-1")
        self.assertEqual(fields["supplier"], "Walk Supplies")
        self.assertEqual(fields["lines"][0]["rate"], 10)

    def test_document_attachment_request_bounds_size(self):
        import frappe

        class FileDoc:
            file_name = "bill.pdf"
            content = b"x" * (intelligence_size + 1) if (intelligence_size := 10 * 1024 * 1024) else b""

            def check_permission(self, perm):
                self.checked = perm

            def get_content(self):
                return self.content

        from erpnext.erp_integrations.pramaan import intelligence

        doc = FileDoc()
        with self.assertRaises(ValueError):
            intelligence.document_attachment_request(doc)

        doc.content = b"%PDF-1.4 small"
        request = intelligence.document_attachment_request(doc)
        self.assertEqual(request["extension"], "pdf")
        self.assertIn("content", request)


if __name__ == "__main__":
    unittest.main()
