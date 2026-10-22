"""Contract and safety tests; every request uses an in-memory fake."""
import unittest
from unittest.mock import patch
from test_pramaan_stubs import boundary, FakeTransport


class ClientTests(unittest.TestCase):
    def test_missing_key_is_clear_and_never_calls_transport(self):
        calls = []
        client = boundary.PramaanClient(api_key="", transport=lambda *args: calls.append(args))
        with self.assertRaises(boundary.MissingPramaanKey) as raised:
            client.call("finance.exchange-rate.get", {})
        self.assertEqual(raised.exception.http_status_code, 422)
        self.assertEqual("Add PRAMAAN_API_KEY to .env", str(raised.exception))
        self.assertFalse(client.configured)
        self.assertEqual(calls, [])

    def test_payment_creates_always_send_the_configured_tax_category(self):
        for capability in ("payments.payment-link.create", "payments.checkout.create"):
            for configured, expected in ((None, "digital_products"), ("", "digital_products"),
                                         ("services", "services")):
                with self.subTest(capability=capability, configured=configured):
                    transport = FakeTransport({"ref": "sandbox-result"})
                    client = boundary.PramaanClient(api_key="fake", transport=transport)
                    body = {"amount": 100, "currency": "GBP"}
                    with patch.dict(boundary.os.environ, {}, clear=True):
                        if configured is not None:
                            boundary.os.environ["PRAMAAN_TAX_CATEGORY"] = configured
                        client.call(capability, body, idempotency_key="invoice-one")
                    self.assertEqual(transport.requests[0][3]["taxCategory"], expected)
                    self.assertEqual(transport.requests[0][2]["Idempotency-Key"], "invoice-one")
                    self.assertNotIn("taxCategory", body)

    def test_estimate_and_call_use_same_body_and_exact_price_limit(self):
        transport = FakeTransport({"can_run": True, "price_max_micro": 1170})
        client = boundary.PramaanClient(api_key="fake", transport=transport)
        body = {"amount": 100, "currency": "GBP"}
        estimate = client.estimate("payments.payment-link.create", body)
        client.call("payments.payment-link.create", body, idempotency_key="once",
                    max_price_micro=estimate["price_max_micro"])
        self.assertTrue(transport.requests[0][1].endswith("/estimate"))
        self.assertEqual(transport.requests[0][3], transport.requests[1][3])
        self.assertEqual(transport.requests[1][2]["Pramaan-Max-Price-Micro"], "1170")

    def test_failed_estimate_never_claims_an_action_may_have_completed(self):
        def unavailable(*args):
            raise boundary.PramaanError("unavailable", uncertain=True)
        client = boundary.PramaanClient(api_key="fake", transport=unavailable)
        with self.assertRaises(boundary.PramaanError) as raised:
            client.estimate("routes.compute", {})
        self.assertFalse(raised.exception.uncertain)
        self.assertNotIn("already have completed", str(raised.exception))

    def test_async_completion_uses_same_job_and_only_one_action(self):
        requests = []
        replies = iter([(202, {"job_id": "job/one", "status": "running"}), (200, {"status": "done", "charged_micro": 1250, "result": {"paymentLink": {"ref": "accepted"}}})])
        def transport(*args):
            requests.append(args)
            return next(replies)
        client = boundary.PramaanClient(api_key="fake", transport=transport, sleep=lambda _: None)
        result = client.call("payments.payment-link.create", {"amount": 100},
                             idempotency_key="saved-key")
        self.assertEqual(result, {"paymentLink": {"ref": "accepted"}})
        self.assertEqual(client.last_job_id, "job/one")
        self.assertEqual(client.last_job_charge_micro, 1250)
        self.assertEqual([r[0] for r in requests], ["POST", "GET"])
        self.assertEqual(requests[0][2]["Idempotency-Key"], "saved-key")
        self.assertTrue(requests[1][1].endswith("/jobs/job%2Fone"))

    def test_uncertain_action_is_not_retried_and_error_is_safe(self):
        calls = []
        def transport(*args):
            calls.append(args)
            raise RuntimeError("vendor secret customer data")
        client = boundary.PramaanClient(api_key="fake", transport=transport)
        with self.assertRaises(boundary.PramaanError) as raised:
            client.call("email.send", {}, idempotency_key="saved")
        self.assertTrue(raised.exception.uncertain)
        self.assertNotIn("secret", str(raised.exception))
        self.assertEqual(len(calls), 1)

    def test_invalid_capabilities_are_rejected_before_transport(self):
        calls = []
        client = boundary.PramaanClient(api_key="fake", transport=lambda *args: calls.append(args))
        for capability in ["invented.capability", "llm.complete", "voice.call.start"]:
            with self.assertRaises(boundary.PramaanError):
                client.run(capability, {})
        self.assertEqual(calls, [])

    def test_redirects_never_forward_credentials(self):
        self.assertIsNone(boundary.NoRedirects().redirect_request(None, None, 302, "", {}, "https://elsewhere.example"))

    def test_configuration_rejects_credentials_and_remote_plain_http(self):
        for url in ["http://remote.example", "https://user:password@example.com", "https://example.com?secret=key"]:
            with self.assertRaises(boundary.PramaanError):
                boundary.PramaanClient(base_url=url)

    def test_invalid_completed_result_is_rejected(self):
        client = boundary.PramaanClient(api_key="fake", sleep=lambda _: None,
            transport=lambda *args: (202, {"job_id": "one", "status": "done", "result": None}))
        with self.assertRaises(boundary.PramaanError):
            client.call("geo.address.geocode", {})

    def test_live_unavailable_signal_becomes_plain_feature_message(self):
        # The live API answers 502 upstream_unavailable (retryable false) when
        # a capability is not available yet; callers only ever see the plain text.
        client = boundary.PramaanClient(api_key="fake", base_url="https://pramaan.test",
            transport=lambda *args: (502, {"error": {"code": "upstream_unavailable", "retryable": False}}))
        with self.assertRaises(boundary.PramaanNotAvailable) as raised:
            client.call("banking.transactions.sync", {}, idempotency_key="sync-test")
        self.assertEqual(str(raised.exception), "Bank feeds are not available yet.")
        self.assertNotIn("upstream", str(raised.exception).lower())
        self.assertNotIn("retryable", str(raised.exception).lower())

    def test_other_defensive_codes_also_stay_plain(self):
        client = boundary.PramaanClient(api_key="fake", base_url="https://pramaan.test",
            transport=lambda *args: (501, {"error": {"code": "not_available_yet"}}))
        with self.assertRaises(boundary.PramaanNotAvailable) as raised:
            client.call("routes.compute", {})
        self.assertEqual(str(raised.exception), "Route planning is not available yet.")
        self.assertNotIn("not_available_yet", str(raised.exception))

    def test_unavailable_outcome_stays_plain(self):
        description = {"available": False}
        client = boundary.PramaanClient(api_key="fake", sleep=lambda _: None)
        with patch.object(boundary.PramaanClient, "outcome_get", return_value=description):
            with self.assertRaises(boundary.OutcomeNotAvailable) as raised:
                client.outcome_run("tax.quote", {"subtotal": 100}, plan="plan",
                                   idempotency_key="key", approved_by="approver")
        self.assertEqual(str(raised.exception), "This outcome is not available yet.")

    def test_upstream_unavailable_during_outcome_run_stays_plain(self):
        description = {"available": True, "requires_approval": True, "effect_class": "external_irreversible"}
        replies = iter([(502, {"error": {"code": "upstream_unavailable", "retryable": False}})])
        client = boundary.PramaanClient(api_key="fake", sleep=lambda _: None,
            transport=lambda *args: next(replies))
        with patch.object(boundary.PramaanClient, "outcome_get", return_value=description):
            with self.assertRaises(boundary.OutcomeNotAvailable):
                client.outcome_run("payments.reconcile", {"cursor": "c"}, plan="plan",
                                   idempotency_key="key", approved_by="approver")

    def test_connection_required_estimate_message(self):
        message = boundary.connection_requirement(
            {"canRun": False, "reason": "connection_required", "slot": "payments"})
        self.assertEqual(message, "Connect the payments account for this service first, then check again.")
        self.assertIsNone(boundary.connection_requirement({"canRun": True}))
        self.assertIsNone(boundary.connection_requirement({"canRun": False, "reason": "other"}))
        self.assertIsNone(boundary.connection_requirement(None))

    def test_error_body_text_never_reaches_callers(self):
        client = boundary.PramaanClient(api_key="fake", base_url="https://pramaan.test",
            transport=lambda *args: (400, {"error": {"code": "invalid_request",
                                                     "message": "private upstream diagnostics"}}))
        with self.assertRaises(boundary.PramaanError) as raised:
            client.call("geo.address.geocode", {})
        self.assertNotIn("private", str(raised.exception))

    def test_outcome_run_requires_approval_and_plan(self):
        description = {"available": True, "requires_approval": True, "effect_class": "external_irreversible"}
        client = boundary.PramaanClient(api_key="fake", sleep=lambda _: None)
        with patch.object(boundary.PramaanClient, "outcome_get", return_value=description):
            with self.assertRaises(boundary.PramaanError) as raised:
                client.outcome_run("invoice.process", {"document": {"text": "x"}})
            self.assertEqual(raised.exception.code, "approval_required")

    def test_outcome_run_rejects_unknown_outcomes_before_transport(self):
        calls = []
        client = boundary.PramaanClient(api_key="fake", transport=lambda *args: calls.append(args))
        with self.assertRaises(boundary.PramaanError):
            client.outcome_run("invented.outcome", {})
        self.assertEqual(calls, [])

    def test_outcome_run_polls_job_and_returns_full_report(self):
        # ASSUMED fixture: the platform types finished outcome results as
        # `unknown`, so the report shape here is an assumption for the fake
        # only; the product surfaces whatever report arrives verbatim.
        requests = []
        replies = iter([(202, {"job_id": "job/nine", "status": "running"}),
                        (200, {"status": "done", "result": {"status": "failed", "steps": []}})])
        def transport(*args):
            requests.append(args)
            return next(replies)
        client = boundary.PramaanClient(api_key="fake", transport=transport, sleep=lambda _: None)
        description = {"available": True, "requires_approval": True, "effect_class": "external_irreversible"}
        with patch.object(boundary.PramaanClient, "outcome_get", return_value=description):
            report = client.outcome_run("invoice.process", {"document": {"text": "x"}}, plan="plan",
                                        idempotency_key="key", approved_by="approver")
        self.assertEqual(report, {"status": "failed", "steps": []})
        self.assertEqual(requests[0][2].get("Pramaan-Plan"), "plan")
        self.assertEqual(requests[0][2].get("Idempotency-Key"), "key")

    def test_social_exchange_returns_verified_claims_only(self):
        client = boundary.PramaanClient(api_key="fake", transport=FakeTransport(
            {"subjectId": "subject", "email": "person@example.com", "emailVerified": True,
             "displayName": "Person", "providerKey": "sign-in-provider"}))
        claims = client.exchange_social_sign_in(provider_key="sign-in-provider", code="one",
                                                redirect_uri="http://localhost:18010/me")
        self.assertEqual(claims["subject_id"], "subject")
        self.assertTrue(claims["email_verified"])
        self.assertNotIn("token", claims)

    def test_social_exchange_refuses_unverified_email(self):
        client = boundary.PramaanClient(api_key="fake", transport=FakeTransport(
            {"subjectId": "subject", "email": "person@example.com", "emailVerified": False}))
        with self.assertRaises(boundary.PramaanError):
            client.exchange_social_sign_in(provider_key="p", code="one", redirect_uri="http://localhost/me")


if __name__ == "__main__":
    unittest.main()
