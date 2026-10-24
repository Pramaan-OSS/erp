"""Payments account module. Public interface: status, connect, session.

One deployment owns one server-configured account. Only its System Managers may
administer it; callers never select an account, key or component permissions.
"""
import hashlib
import json
import logging
import re
import uuid

import frappe
from pramaan import Pramaan
from pramaan import PramaanError as SDKPramaanError
from pramaan.payments import payments_account_session

from erpnext.erp_integrations.pramaan import get_client
from erpnext.pramaan import PramaanError

SETUP_PATH = "/app/payments-account"
COMPONENTS = ["account_onboarding", "account_management", "notification_banner", "payments", "payouts", "balances"]
REQUIREMENTS = {
    "external_account": "Add a bank account for payouts",
    "tos_acceptance": "Accept the account terms",
    "business_profile": "Complete your business details",
    "company": "Complete your company details",
    "individual": "Complete your personal details",
    "representative": "Confirm the account representative",
    "owners": "Confirm the business owners",
    "directors": "Confirm the company directors",
    "verification": "Provide documents to verify your details",
    "onboarding": "Complete account setup",
}


def connection_hint():
    return 'Connect your payments account first. <a href="' + SETUP_PATH + '">Open Payments account</a>.'


def _admin():
    if frappe.session.user == "Guest":
        frappe.throw("Sign in as an administrator to manage the payments account.", frappe.PermissionError)
    frappe.only_for("System Manager")


def _client():
    client = get_client()
    if not client._uses_fake_transport:
        client.require_configured()
    return client


def _failure():
    frappe.throw("Could not open your payments account. Refresh the page and try again.")


def _intent_key(client):
    # A changed deployment credential invalidates the previous approval.
    scope = hashlib.sha256(client._api_key.encode()).hexdigest()
    return "payments-account-setup:" + frappe.session.user + ":" + scope


@frappe.whitelist(methods=["POST"])
def status():
    _admin()
    try:
        result = _client().call("payments.account.status", {})
    except PramaanError as error:
        if error.code == "connection_required":
            return {"state": "not_connected", "chargesEnabled": False, "payoutsEnabled": False, "requirements": []}
        _failure()
    due = result.get("requirementsDue") or []
    if not isinstance(due, list):
        due = []
    labels = list(dict.fromkeys(REQUIREMENTS.get(str(item).split('.')[0], "Review the remaining account details") for item in due))
    ready = result.get("status") == "ready" and result.get("chargesEnabled") is True and result.get("payoutsEnabled") is True
    return {"state": "ready" if ready else "incomplete", "chargesEnabled": result.get("chargesEnabled") is True,
            "payoutsEnabled": result.get("payoutsEnabled") is True, "requirements": labels}


@frappe.whitelist(methods=["POST"])
def connect(confirmation: str | None = None, country: str = ""):
    _admin()
    client = _client()
    url = frappe.utils.get_url() + SETUP_PATH
    body = {"returnUrl": url, "refreshUrl": url}
    if country:
        if not re.fullmatch(r"[A-Za-z]{2}", country):
            frappe.throw("Enter a two-letter business country code.")
        body["country"] = country.upper()
    key = _intent_key(client)
    try:
        if not confirmation:
            estimate = client.estimate("payments.account.connect", body)
            if estimate.get("can_run", estimate.get("canRun")) is not True:
                _failure()
            token = str(uuid.uuid4())
            frappe.cache.set_value(key, {"token": token, "body": body, "idempotency_key": str(uuid.uuid4())}, expires_in_sec=600)
            return {"confirmation": token}
        intent = frappe.cache.get_value(key)
        if not intent or intent.get("token") != confirmation or intent.get("body") != body:
            frappe.throw("Review account setup again before continuing.")
        result = client.call("payments.account.connect", body, idempotency_key=intent['idempotency_key'])
        # Keep the intent on failure so a retry cannot create a second account.
        if result.get("onboardingMode") == "embedded":
            reply = {"mode": "embedded"}
        elif isinstance(result.get("onboardingUrl"), str):
            from urllib.parse import urlparse
            parsed = urlparse(result['onboardingUrl'])
            if parsed.scheme != 'https' or parsed.username or parsed.password:
                _failure()
            reply = {"mode": "hosted", "onboardingUrl": result['onboardingUrl']}
        else:
            _failure()
        frappe.cache.delete_value(key)
        return reply
    except PramaanError:
        _failure()


def create_account_session():
    """Create a fresh package session using the deployment's configured identity."""
    client = _client()
    if client._uses_fake_transport:
        # The fixture has no embedded components; never reach the network.
        raise PramaanError("unavailable")
    try:
        with Pramaan(client._api_key, base_url=client._base_url) as sdk:
            result = payments_account_session(sdk, components=COMPONENTS)
    except SDKPramaanError as error:
        # Normalize package errors without retaining upstream messages or secrets.
        code = error.code if error.code in {"forbidden", "connection_required"} else "unavailable"
    else:
        secret, public = result.get("clientSecret"), result.get("publishableKey")
        if isinstance(secret, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,4096}", secret) \
                and isinstance(public, str) and re.fullmatch(r"pk_(test|live)_[A-Za-z0-9]{1,255}", public):
            return {"clientSecret": secret, "publishableKey": public}
        code = "invalid_response"
    raise PramaanError(code)


@frappe.whitelist(methods=["POST"])
def session():
    _admin()
    try:
        return create_account_session()
    except Exception as error:
        # Only fixed metadata: never exception text, response bodies or tracebacks.
        code = error.code if isinstance(error, PramaanError) else "unexpected_error"
        if code not in {"forbidden", "approval_required", "request_rejected", "unavailable",
                        "invalid_response", "connection_required", "missing_api_key", "unexpected_error"}:
            code = "unavailable"
        logging.getLogger(__name__).warning(
            "Payments account session failed: exception_class=%s pramaan_code=%s",
            type(error).__name__, code)
        # Leave the exception context before raising a public validation error.
    _failure()


def browser_response(response):
    """Thin response adapter: no-store, a fixed local guidance link, and runtime CSP."""
    if response is None:
        return
    path = getattr(frappe.request, 'path', '')
    command = getattr(frappe, 'form_dict', {}).get('cmd', '') or ''
    if ('/api/' in path and '/' + __name__ + '.' in path) or command.startswith(__name__ + '.'):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    if response.status_code >= 400 and response.is_json:
        body = response.get_json(silent=True) or {}
        messages = str(body.get('_server_messages', ''))
        hints = ('Connect your payments account', 'Connect the payments account', 'Connect the fee payments account')
        if any(hint in messages for hint in hints):
            body['_server_messages'] = json.dumps([json.dumps({'message': connection_hint()})])
            body['message'] = connection_hint()
            response.set_data(json.dumps(body))
    # Connect.js is the single approved browser integration exception. The runtime
    # needs its component frames and images as well as the entry script.
    policy = response.headers.get('Content-Security-Policy', '')
    if policy:
        policy = policy.replace("script-src 'self'", "script-src 'self' https://connect-js.stripe.com https://js.stripe.com")
        policy = policy.replace("frame-src 'self'", "frame-src 'self' https://connect-js.stripe.com https://js.stripe.com")
        policy = policy.replace("img-src 'self'", "img-src 'self' https://*.stripe.com")
        response.headers['Content-Security-Policy'] = policy
    return response
