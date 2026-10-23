"""All outside service calls go through this server-side module."""
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import ClassVar, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

Feature = Literal[
    "email_sending", "social_sign_in", "bank_feeds", "routing", "sms",
    "payment_links", "addresses", "shipping", "company_data", "tax_data",
    "document_intake", "currency_rates", "invoice_intake",
]


class CapabilityUnavailable(RuntimeError):
    """A stable application error safe to show without request data or secrets."""

    code = "capability_unavailable"

    def __init__(self, feature: Feature):
        self.feature = feature
        messages = {
            "email_sending": "Email sending is not set up yet. Add PRAMAAN_API_KEY to .env.",
            "social_sign_in": "Social sign-in is not available yet. Use password sign-in.",
            "bank_feeds": "Bank feeds are not available yet.",
            "routing": "Route planning is not available yet.",
            "sms": "Text messages are not available yet.",
            "payment_links": "Payment links are not available yet.",
            "addresses": "Address checks are not available yet.",
            "shipping": "Shipping is not available yet.",
            "company_data": "Company details lookups are not available yet.",
            "tax_data": "Tax data lookups are not available yet.",
            "document_intake": "Document reading is not available yet.",
            "currency_rates": "Exchange rates are not available yet.",
            "invoice_intake": "Invoice reading is not available yet.",
            "india_e_invoicing": "India e-invoicing is not available yet.",
        }
        super().__init__(messages[feature])


@dataclass(frozen=True)
class FeatureAvailability:
    feature: Feature
    enabled: bool
    reason: str


class PramaanError(RuntimeError):
    """Normalized error: never expose an upstream body, provider or secret."""

    def __init__(self, code="unavailable", *, uncertain=False, job_id=None):
        self.code = code
        self.uncertain = uncertain
        self.job_id = job_id
        super().__init__(
            "The action may already have completed. Check its status before trying again."
            if uncertain else "Pramaan could not complete this request."
        )


MISSING_KEY_MESSAGE = "Add PRAMAAN_API_KEY to .env"


class MissingPramaanKey(PramaanError):
    http_status_code = 422

    def __init__(self):
        super().__init__("missing_api_key")
        self.args = (MISSING_KEY_MESSAGE,)


class PramaanNotAvailable(PramaanError):
    http_status_code = 503

    def __init__(self, capability):
        super().__init__("not_available_yet")
        for prefix, surface in (
            ("banking.", "Bank feeds"), ("routes.", "Route planning"), ("sms.", "Text messages"),
            ("payments.", "Payments"), ("geo.", "Address checks"), ("shipping.", "Shipping"),
            ("companies.", "Company details"), ("finance.", "Tax and currency data"),
            ("india.", "India e-invoicing"),
            ("document.", "Document reading"), ("email.", "Email"), ("auth.", "Social sign-in"),
        ):
            if capability.startswith(prefix):
                self.args = (f"{surface} are not available yet." if surface.endswith("s") and not surface.endswith("ss") else f"{surface} is not available yet.",)
                return
        self.args = ("This service is not available yet.",)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


UNAVAILABLE_CODES = frozenset({"upstream_unavailable", "not_available_yet", "not_available",
    "capability_unavailable", "not_implemented", "unsupported_capability"})


class OutcomeNotAvailable(PramaanError):
    http_status_code = 503

    def __init__(self):
        super().__init__("not_available_yet")
        self.args = ("This outcome is not available yet.",)


def connection_requirement(estimate):
    """A plain message when an estimate needs a connected account, else None.

    The platform marks such estimates `canRun: false` with reason
    `connection_required` and the connection slot that is missing. The slot
    name is the platform's own; no provider is ever named.
    """
    if not isinstance(estimate, dict):
        return None
    if estimate.get("canRun") is not False or estimate.get("reason") != "connection_required":
        return None
    slot = str(estimate.get("slot") or "").strip() or "account"
    return f"Connect the {slot} account for this service first, then check again."


def payment_tax_category():
    return os.environ.get("PRAMAAN_TAX_CATEGORY", "").strip() or "digital_products"


class PramaanClient:
    """Single server-side HTTP client. Mutating requests are never retried."""

    CAPABILITIES = frozenset({
        "payments.account.status", "payments.account.connect", "payments.account.session.create",
        "payments.transfer-request.create", "payments.transfer-request.get",
        "payments.transfer-request.list", "payments.transfer-request.cancel",
        "finance.exchange-rate.get", "finance.exchange-rate.history",
        "finance.vat-number.validate", "finance.tax-rates.get", "finance.vat-rates.get",
        "banking.connection.start", "banking.connection.status", "banking.accounts.list",
        "banking.transactions.sync", "banking.transactions.list", "banking.account.balances.get",
        "banking.institutions.search",
        "routes.compute", "routes.stops.sequence",
        "sms.send",
        "payments.payment-link.create", "payments.checkout.create",
        "payments.payment.get", "payments.payment-link.orders.list",
        "email.send", "email.template.send", "email.message.send", "email.message.reply",
        "auth.social.exchange",
        "geo.address.validate", "geo.address.parse", "geo.address.geocode",
        "shipping.label.purchase", "shipping.container.track", "shipping.delivery.estimate",
        "companies.enrich", "companies.domain.find", "companies.tax-identifiers.list",
        "document.extract",
        "india.gst.consent.create",
        "india.gst.einvoice.create", "india.gst.einvoice.get",
        "india.gst.einvoice.cancel", "india.gst.einvoice.qr.get",
    })
    ACTIONS = frozenset({
        "payments.account.connect", "payments.account.session.create",
        "payments.transfer-request.create", "payments.transfer-request.cancel",
        "sms.send",
        "payments.payment-link.create", "payments.checkout.create",
        "email.send", "email.template.send", "email.message.send", "email.message.reply",
        "banking.connection.start", "banking.transactions.sync", "auth.social.exchange", "shipping.label.purchase",
        "india.gst.consent.create", "india.gst.einvoice.create", "india.gst.einvoice.cancel",
    })
    OUTCOMES = frozenset({"invoice.process", "tax.quote", "payments.reconcile"})

    def __init__(self, *, api_key=None, base_url=None, transport=None, sleep=time.sleep):
        self._api_key = api_key if api_key is not None else os.environ.get("PRAMAAN_API_KEY", "")
        self._base_url = (base_url or os.environ.get("PRAMAAN_BASE_URL") or "https://api.pramaan.dev").rstrip("/")
        parsed = urlparse(self._base_url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "fake-pramaan"}
        ):
            raise PramaanError("invalid_configuration")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise PramaanError("invalid_configuration")
        self._transport = transport or (self._fake if os.environ.get("PRAMAAN_FAKE") == "1" else self._http)
        self._sleep = sleep
        self.last_charge_micro = None
        self.last_job_id = None
        self.last_job_charge_micro = None

    @property
    def configured(self):
        return bool(self._api_key.strip())

    def require_configured(self):
        if not self.configured:
            raise MissingPramaanKey()

    @staticmethod
    def _fake(method, url, headers, body):
        # Explicit local fixture mode has no network transport or outside effects.
        return 503, {"error": {"code": "upstream_unavailable", "retryable": False}}

    def _http(self, method, url, headers, body):
        request = Request(url, data=body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None,
                          headers=headers, method=method)
        try:
            with build_opener(NoRedirects()).open(request, timeout=120 if url.endswith("/document.extract") else 30) as response:
                self.last_charge_micro = response.headers.get("X-Pramaan-Price-Micro")
                raw = response.read(16_000_001)
                if len(raw) > 16_000_000:
                    raise PramaanError("invalid_response")
                return response.status, json.loads(raw)
        except HTTPError as error:
            self.last_charge_micro = error.headers.get("X-Pramaan-Price-Micro")
            # Read only bounded, recognized error codes; never surface the upstream body.
            code = None
            try:
                payload = json.loads(error.read(16_001))
                inner = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(inner, dict):
                    code = inner.get("code")
                elif isinstance(inner, str):
                    code = inner
                elif isinstance(payload, dict):
                    code = payload.get("code")
            except (ValueError, OSError):
                code = None
            return error.code, {"error": code if isinstance(code, str) and code in UNAVAILABLE_CODES | {"connection_required", "forbidden", "approval_required"} else None}
        except (URLError, OSError, ValueError):
            raise PramaanError("unavailable", uncertain=method == "POST") from None

    def _request(self, method, path, body=None, *, idempotency_key=None, approved_by=None, account=None, plan=None, outcome=False, capability=None, max_price_micro=None):
        self.require_configured()
        headers = {"Authorization": "Bearer " + self._api_key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if max_price_micro is not None:
            if not isinstance(max_price_micro, int) or max_price_micro < 0:
                raise PramaanError("invalid_price_limit")
            headers["Pramaan-Max-Price-Micro"] = str(max_price_micro)
        if approved_by:
            headers["Pramaan-Approved-By"] = approved_by
        if account:
            headers["Pramaan-Account"] = account
        if plan:
            headers["Pramaan-Plan"] = plan
        try:
            status, result = self._transport(method, self._base_url + path, headers, body)
        except PramaanError:
            raise
        except Exception:
            raise PramaanError("unavailable", uncertain=method == "POST") from None
        if status >= 400:
            remote_code = result.get("error") if isinstance(result, dict) else None
            if isinstance(remote_code, dict):
                remote_code = remote_code.get("code")
            if not remote_code and isinstance(result, dict):
                remote_code = result.get("code")
            if remote_code == "connection_required":
                error = PramaanError("connection_required")
                error.args = ("Connect your payments account first, then try again.",)
                raise error
            if capability and (status == 501 or isinstance(remote_code, str) and remote_code in UNAVAILABLE_CODES):
                raise PramaanNotAvailable(capability)
            code = remote_code if isinstance(remote_code, str) and remote_code in {"forbidden", "approval_required"} else "request_rejected"
            uncertain = method == "POST" and status >= 500
            if outcome:
                code = {403: "approval_required", 409: "plan_changed", 429: "try_later"}.get(status, code)
                if status == 502 and remote_code == "upstream_unavailable":
                    code, uncertain = "upstream_unavailable", False
            raise PramaanError(code, uncertain=uncertain)
        if status not in {200, 201, 202} or not isinstance(result, dict):
            raise PramaanError("invalid_response", uncertain=method == "POST")
        return status, result

    def run(self, capability, inputs, *, idempotency_key=None, approved_by=None, max_price_micro=None):
        self.require_configured()
        if capability not in self.CAPABILITIES:
            raise PramaanError("unsupported_capability")
        if capability in self.ACTIONS and not idempotency_key:
            raise PramaanError("missing_idempotency_key")
        if capability in {"payments.payment-link.create", "payments.checkout.create"}:
            inputs = {**inputs, "taxCategory": payment_tax_category()}
        status, result = self._request("POST", "/v1/capabilities/" + quote(capability, safe=""), inputs,
                                       idempotency_key=idempotency_key, approved_by=approved_by, capability=capability, max_price_micro=max_price_micro)
        if status == 202:
            if not isinstance(result.get("job_id"), str) or result.get("status") not in {"running", "done", "failed", "cancelled"}:
                raise PramaanError("invalid_response", uncertain=capability in self.ACTIONS)
        return result

    def estimate(self, capability, inputs):
        """Estimate the exact capability body without running it."""
        if capability not in self.CAPABILITIES:
            raise PramaanError("unsupported_capability")
        if capability in {"payments.payment-link.create", "payments.checkout.create"}:
            inputs = {**inputs, "taxCategory": payment_tax_category()}
        try:
            _, result = self._request("POST", "/v1/capabilities/" + quote(capability, safe="") + "/estimate", inputs)
        except PramaanError as error:
            if error.uncertain:
                # Estimates never perform an action, even if their reply is lost.
                raise PramaanError(error.code) from None
            raise
        return result

    def upload_file(self, content, content_type, *, idempotency_key):
        self.require_configured()
        headers = {"Authorization": "Bearer " + self._api_key, "Content-Type": content_type,
                   "Idempotency-Key": idempotency_key, "Accept": "application/json"}
        status, result = self._transport("POST", self._base_url + "/v1/files?kind=document", headers, content)
        if status not in {200, 201} or not isinstance(result, dict) or not result.get("fileId"):
            raise PramaanError("upload_failed")
        return result

    def job(self, job_id):
        _, result = self._request("GET", "/v1/jobs/" + quote(job_id, safe=""))
        charged = result.get("charged_micro")
        if isinstance(charged, int) and charged >= 0:
            self.last_job_charge_micro = charged
        return result

    def call(self, capability, inputs, *, idempotency_key=None, approved_by=None, max_polls=60, max_price_micro=None):
        self.last_job_id = None
        self.last_job_charge_micro = None
        result = self.run(capability, inputs, idempotency_key=idempotency_key, approved_by=approved_by, max_price_micro=max_price_micro)
        if "job_id" not in result:
            return result
        job_id = result["job_id"]
        self.last_job_id = job_id
        for _ in range(max_polls):
            state = result.get("status")
            if state == "done":
                completed = result.get("result")
                if not isinstance(completed, dict):
                    raise PramaanError("invalid_response", uncertain=capability in self.ACTIONS)
                return completed
            if state in {"failed", "cancelled"}:
                raise PramaanError("job_failed", uncertain=capability in self.ACTIONS)
            if state != "running":
                raise PramaanError("invalid_response")
            self._sleep(2)
            result = self.job(job_id)
        raise PramaanError("job_pending", uncertain=capability in self.ACTIONS)

    def new_idempotency_key(self):
        return str(uuid.uuid4())

    def outcomes_list(self):
        """List the platform's outcome descriptions without running anything."""
        _, result = self._request("GET", "/v1/outcomes", outcome=True)
        return result

    def outcome_get(self, outcome_id):
        _, result = self._request("GET", "/v1/outcomes/" + quote(outcome_id, safe=""), outcome=True)
        return result

    def outcome_estimate(self, outcome_id, body):
        """Return steps, worst-case cost and plan for the exact run body; no charge."""
        _, result = self._request("POST", "/v1/outcomes/" + quote(outcome_id, safe="") + "/estimate",
                                  body, outcome=True)
        return result

    def outcome_run(self, outcome_id, body, *, plan=None, idempotency_key=None,
                    approved_by=None, max_polls=60):
        """Run an explicitly reviewed body once, preserving the complete run report.

        Pass the estimate's plan only after human approval. A stale or changed plan
        requires another estimate and approval; neither requests nor failed runs
        are retried here.
        """
        if outcome_id not in self.OUTCOMES:
            raise PramaanError("unsupported_capability")
        description = self.outcome_get(outcome_id)
        if description.get("available") is False:
            raise OutcomeNotAvailable()
        if description.get("available") is not True:
            raise PramaanError("invalid_response")
        if description.get("requires_approval") and not plan:
            raise PramaanError("approval_required")
        if description.get("effect_class") != "read_only" and not idempotency_key:
            raise PramaanError("missing_idempotency_key")
        try:
            status, result = self._request("POST", "/v1/outcomes/" + quote(outcome_id, safe=""), body,
                                           plan=plan, idempotency_key=idempotency_key,
                                           approved_by=approved_by, outcome=True)
        except PramaanError as error:
            # A 502 upstream_unavailable means the outcome cannot run now.
            if error.code == "upstream_unavailable":
                raise OutcomeNotAvailable() from None
            raise
        if status == 202:
            job_id = result.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise PramaanError("invalid_response", uncertain=True)
            for poll in range(max_polls + 1):
                state = result.get("status")
                if state in {"done", "failed", "cancelled"}:
                    report = result.get("result")
                    if not isinstance(report, dict):
                        raise PramaanError("invalid_response", uncertain=True)
                    return self._outcome_report(report)
                if state not in {"running", "queued"}:
                    raise PramaanError("invalid_response", uncertain=True)
                if poll == max_polls:
                    break
                self._sleep(2)
                try:
                    result = self.job(job_id)
                except PramaanError:
                    # The accepted run may still be acting; never start another.
                    raise PramaanError("job_pending", uncertain=True, job_id=job_id) from None
            raise PramaanError("job_pending", uncertain=True, job_id=job_id)
        return self._outcome_report(result)

    @staticmethod
    def _outcome_report(report):
        if report.get("status") not in {"done", "failed", "declined"}:
            raise PramaanError("invalid_response", uncertain=True)
        # Failed reports may contain completed or unknown effects. Return them
        # intact for review; they must not be mistaken for fallback permission.
        return report

    # Feature contracts each stay false until their integration and fake
    # checks are in place; live platform status decides the rest.
    FEATURES: ClassVar[dict[str, bool]] = {
        "email_sending": True,
        "social_sign_in": True,
        "bank_feeds": False,
        "routing": False,
        "sms": False,
        "payment_links": False,
        "addresses": False,
        "shipping": False,
        "company_data": False,
        "tax_data": False,
        "document_intake": False,
        "currency_rates": False,
        "invoice_intake": False,
        "india_e_invoicing": False,
    }

    def availability(self):
        return tuple(
            FeatureAvailability(feature, enabled, "" if enabled else str(CapabilityUnavailable(feature)))
            for feature, enabled in self.FEATURES.items()
        )

    def exchange_social_sign_in(self, *, provider_key, code, redirect_uri,
                                pkce_verifier=None, expected_nonce=None, account=None):
        """Redeem a single-use sign-in code for verified identity claims.

        Upstream credentials never pass through here: the platform returns
        claims only, and the application keeps no authorization secrets.
        """
        inputs = {"providerKey": provider_key, "code": code, "redirectUri": redirect_uri}
        if pkce_verifier:
            inputs["pkceVerifier"] = pkce_verifier
        if expected_nonce:
            inputs["expectedNonce"] = expected_nonce
        _, result = self._request("POST", "/v1/capabilities/auth.social.exchange",
                                  inputs, account=account, idempotency_key=self.new_idempotency_key())
        if not isinstance(result.get("subjectId"), str) or not result.get("subjectId"):
            raise PramaanError("invalid_response")
        claims = {
            "provider_key": result.get("providerKey", provider_key),
            "subject_id": result["subjectId"],
            "email": result.get("email") or "",
            "email_verified": result.get("emailVerified") is True,
            "display_name": result.get("displayName") or "",
        }
        if not claims["email"] or not claims["email_verified"]:
            raise PramaanError("identity_unverified")
        return claims
