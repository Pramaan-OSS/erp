"""India e-invoicing contract checks; every call uses a fake client."""
import unittest

from test_integration_contracts import install_frappe_stub  # noqa: F401

from erpnext.erp_integrations.pramaan import india_gst


def sample_seller(**overrides):
    base = {
        "gstin": "27AAPFU0939F1ZV",
        "legal_name": "ERP India Pvt Ltd",
        "address_line1": "12 Baner Road",
        "address_line2": "",
        "city": "Pune",
        "pincode": "411045",
        "state": "Maharashtra",
    }
    base.update(overrides)
    return base


def sample_buyer(**overrides):
    base = {
        "gstin": "29AABCU9603R1ZM",
        "legal_name": "Buyer Traders",
        "address_line1": "5 MG Road",
        "address_line2": "",
        "city": "Bengaluru",
        "pincode": "560001",
        "state": "Karnataka",
    }
    base.update(overrides)
    return base


def sample_items(**overrides):
    row = {
        "line_number": 1,
        "description": "Widget",
        "hsn_code": "8479",
        "is_service": False,
        "quantity": 2,
        "unit": "NOS",
        "unit_price": 500.0,
        "gross_amount": 1000.0,
        "taxable_amount": 1000.0,
        "gst_rate": 18.0,
        "total_amount": 1180.0,
    }
    row.update(overrides)
    return [row]


def sample_totals(**overrides):
    base = {
        "taxable_value": 1000.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "igst": 180.0,
        "cess": 0.0,
        "round_off": 0.0,
        "invoice_value": 1180.0,
    }
    base.update(overrides)
    return base


SAMPLE_DOCUMENT = {"number": "ACC-SINV-2026-0001", "date": "2026-10-16"}


class ConsentTests(unittest.TestCase):
    def test_consent_request_forwards_credentials_once(self):
        body = india_gst.consent_request("27aapfu0939f1zv", " portal-user ", "secret-1")
        self.assertEqual(body["gstin"], "27AAPFU0939F1ZV")
        self.assertEqual(body["services"], ["einvoice"])
        self.assertEqual(body["einvoiceCredentials"], {"username": "portal-user", "password": "secret-1"})
        with self.assertRaises(ValueError):
            india_gst.consent_request("", "user", "secret")

    def test_consent_ref_requires_a_reference(self):
        self.assertEqual(india_gst.consent_ref({"ref": "consent-1"}), "consent-1")
        with self.assertRaises(ValueError):
            india_gst.consent_ref({"status": "active"})


class InvoiceRequestTests(unittest.TestCase):
    def test_inter_state_invoice_has_igst_and_place_of_supply(self):
        body = india_gst.invoice_request(
            sample_seller(), sample_buyer(), sample_items(), sample_totals(), SAMPLE_DOCUMENT
        )
        self.assertEqual(body["seller"]["stateCode"], "27")
        self.assertEqual(body["buyer"]["stateCode"], "29")
        self.assertEqual(body["buyer"]["placeOfSupply"], "29")
        self.assertEqual(body["items"][0]["igstAmt"], 180.0)
        self.assertNotIn("cgstAmt", body["items"][0])
        self.assertEqual(body["totals"]["invoiceValue"], 1180.0)
        self.assertEqual(body["document"]["type"], "INV")

    def test_intra_state_invoice_splits_cgst_sgst(self):
        buyer = sample_buyer(state="Maharashtra", city="Mumbai", pincode="400001")
        body = india_gst.invoice_request(
            sample_seller(), buyer, sample_items(), {**sample_totals(), "igst": 0.0, "cgst": 90.0, "sgst": 90.0},
            SAMPLE_DOCUMENT,
        )
        self.assertEqual(body["items"][0]["cgstAmt"], 90.0)
        self.assertEqual(body["items"][0]["sgstAmt"], 90.0)
        self.assertNotIn("igstAmt", body["items"][0])

    def test_unregistered_buyer_becomes_urp(self):
        buyer = sample_buyer(gstin="")
        body = india_gst.invoice_request(
            sample_seller(), buyer, sample_items(), sample_totals(), SAMPLE_DOCUMENT
        )
        self.assertEqual(body["buyer"]["gstin"], "URP")

    def test_local_validation_errors_name_the_missing_field(self):
        with self.assertRaisesRegex(ValueError, "HSN"):
            india_gst.invoice_request(
                sample_seller(), sample_buyer(), sample_items(hsn_code=""), sample_totals(), SAMPLE_DOCUMENT
            )
        with self.assertRaisesRegex(ValueError, "GST rate"):
            india_gst.invoice_request(
                sample_seller(), sample_buyer(), sample_items(gst_rate=None), sample_totals(), SAMPLE_DOCUMENT
            )
        with self.assertRaisesRegex(ValueError, "one GST rate"):
            india_gst.invoice_request(
                sample_seller(),
                sample_buyer(),
                [sample_items()[0], sample_items()[0].copy() | {"line_number": 2, "gst_rate": 5.0}],
                sample_totals(),
                SAMPLE_DOCUMENT,
            )
        with self.assertRaisesRegex(ValueError, "recognized Indian state"):
            india_gst.invoice_request(
                sample_seller(), sample_buyer(state="Bavaria"), sample_items(), sample_totals(), SAMPLE_DOCUMENT
            )
        with self.assertRaisesRegex(ValueError, "total"):
            india_gst.invoice_request(
                sample_seller(), sample_buyer(), sample_items(), {**sample_totals(), "invoice_value": None},
                SAMPLE_DOCUMENT,
            )


class RegistrationTests(unittest.TestCase):
    def test_registration_result_normalizes(self):
        normalized = india_gst.registration_result({
            "status": "Active", "irn": "IRN-1", "acknowledgementNumber": "112010036583631",
            "acknowledgedAt": "2026-10-16T10:00:00", "signedInvoice": "abc", "signedQr": "qr",
            "ewaybillNumber": "301000123456", "ref": "einv-1",
        })
        self.assertEqual(normalized["irn"], "IRN-1")
        self.assertEqual(normalized["einvoice_ref"], "einv-1")
        self.assertEqual(normalized["signed_qr"], "qr")
        with self.assertRaisesRegex(ValueError, "reference number"):
            india_gst.registration_result({"status": "Err"})

    def test_cancel_request_whitelists_reasons_and_needs_remarks(self):
        body = india_gst.cancel_request("einv-1", "3", "Order cancelled")
        self.assertEqual(body, {"ref": "einv-1", "reason": "3", "remarks": "Order cancelled"})
        with self.assertRaises(ValueError):
            india_gst.cancel_request("einv-1", "9", "Order cancelled")
        with self.assertRaises(ValueError):
            india_gst.cancel_request("einv-1", "2", "  ")


class ClientWiringTests(unittest.TestCase):
    def test_india_capabilities_are_declared_and_gated(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("pramaan_boundary", str(
            __import__("pathlib").Path(__file__).resolve().parents[1] / "erpnext" / "pramaan.py"))
        boundary = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(boundary)

        for capability in ("india.gst.consent.create", "india.gst.einvoice.create",
                           "india.gst.einvoice.get", "india.gst.einvoice.cancel",
                           "india.gst.einvoice.qr.get"):
            self.assertIn(capability, boundary.PramaanClient.CAPABILITIES)
        for action in ("india.gst.consent.create", "india.gst.einvoice.create", "india.gst.einvoice.cancel"):
            self.assertIn(action, boundary.PramaanClient.ACTIONS)
        # the register/cancel actions cannot run without an idempotency key
        client = boundary.PramaanClient(api_key="fake", transport=lambda *a: (200, {}))
        for action in ("india.gst.einvoice.create", "india.gst.einvoice.cancel", "india.gst.consent.create"):
            with self.assertRaises(boundary.PramaanError):
                client.run(action, {})

    def test_unavailable_einvoicing_is_plain(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("pramaan_boundary", str(
            __import__("pathlib").Path(__file__).resolve().parents[1] / "erpnext" / "pramaan.py"))
        boundary = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(boundary)

        client = boundary.PramaanClient(api_key="fake", base_url="https://pramaan.test",
            transport=lambda *a: (502, {"error": {"code": "upstream_unavailable", "retryable": False}}))
        with self.assertRaises(boundary.PramaanNotAvailable) as raised:
            client.call("india.gst.einvoice.create", {"ref": "c", "invoice": {}}, idempotency_key="k")
        self.assertEqual(str(raised.exception), "India e-invoicing is not available yet.")


if __name__ == "__main__":
    unittest.main()
