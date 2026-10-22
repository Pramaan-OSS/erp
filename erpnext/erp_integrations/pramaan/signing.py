"""Social sign-in through the single Pramaan boundary.

The browser only ever sees an authorization URL and a one-time code. No
client secret enters this app: the code is redeemed server-side by the
Pramaan client, which returns verified identity claims only. A local session
starts only after a verified exchange with a verified email address.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import frappe
from frappe import _

from erpnext.pramaan import PramaanError

STATE_MAX_AGE = 600
STATE_COOKIE = "pramaan_signin"
# OpenID providers verify a nonce in the signed token; the catalogue's other
# sign-in accounts refuse one.
NONCE_PROVIDERS = {"google", "microsoft", "apple"}
PKCE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def _config():
	values = frappe._dict(frappe.db.get_singles_dict("Sign-In Settings", cast=True))
	enabled = bool(values.get("enabled"))
	provider_key = (values.get("provider_key") or "").strip()
	client_id = (values.get("client_id") or "").strip()
	authorize_url = (values.get("authorize_url") or "").strip()
	scope = (values.get("scope") or "").strip()
	use_pkce = bool(values.get("use_pkce"))
	if enabled and not (provider_key and client_id and authorize_url):
		frappe.throw(_("Social sign-in is configured incompletely."), frappe.ValidationError)
	return enabled, provider_key, client_id, authorize_url, scope, use_pkce


def _state_signature(payload: bytes) -> str:
	return hmac.new(frappe.utils.password.get_encryption_key().encode(), payload, hashlib.sha256).hexdigest()


def _redirect_uri() -> str:
	return frappe.utils.get_url("/api/method/erpnext.erp_integrations.pramaan.signing.callback")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def status():
	enabled = bool(frappe.db.get_single_value("Sign-In Settings", "enabled"))
	return {"enabled": enabled}


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def start_redirect():
	"""Send the visitor to the sign-in account's own authorization page."""
	result = start()
	frappe.local.flags.redirect_location = result["authorizeUrl"]
	raise frappe.Redirect


@frappe.whitelist(allow_guest=True, methods=["GET"])
def start():
	"""Build the authorization redirect. State and PKCE never leave cookies."""
	enabled, provider_key, client_id, authorize_url, scope, use_pkce = _config()
	if not enabled:
		frappe.throw(_("Social sign-in is not available. Use password sign-in."), frappe.PermissionError)
	parsed = urlparse(authorize_url)
	if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
		frappe.throw(_("The authorization endpoint must be an https address."), frappe.ValidationError)
	issued = int(time.time())
	nonce = secrets.token_urlsafe(16) if provider_key in NONCE_PROVIDERS else ""
	verifier = "".join(secrets.choice(PKCE_ALPHABET) for _ in range(64)) if use_pkce else ""
	state = base64.urlsafe_b64encode(json.dumps({"t": issued, "p": provider_key}).encode()).decode().rstrip("=")
	state = state + "." + _state_signature(state.encode())
	cookie = {"state": state, "nonce": nonce, "issued": issued}
	if verifier:
		cookie["verifier"] = verifier
	frappe.local.cookie_manager.set_cookie(STATE_COOKIE, json.dumps(cookie),
										   httponly=True, samesite="Lax", max_age=STATE_MAX_AGE)
	params = dict(parse_qsl(parsed.query))
	params.update({"client_id": client_id, "redirect_uri": _redirect_uri(),
				   "response_type": "code", "scope": scope, "state": state})
	if verifier:
		params["code_challenge"] = base64.urlsafe_b64encode(
			hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
		params["code_challenge_method"] = "S256"
	if nonce:
		params["nonce"] = nonce
	target = urlunparse(parsed._replace(query=urlencode(params)))
	return {"authorizeUrl": target}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def callback(code: str = "", state: str = "", error: str = "", redirect_to: str = ""):
	"""Redeem the returned code through Pramaan and open a local session."""
	landing = redirect_to if redirect_to.startswith("/app") else "/app"

	def refuse(reason):
		frappe.local.cookie_manager.delete_cookie(STATE_COOKIE)
		frappe.local.flags.redirect_location = "/login?social=" + reason
		raise frappe.Redirect

	if error:
		return refuse("cancelled")
	raw = frappe.request.cookies.get(STATE_COOKIE, "") if frappe.request else ""
	try:
		cookie = json.loads(raw)
	except ValueError:
		cookie = {}
	if not code or not state or not isinstance(cookie, dict) or cookie.get("state") != state:
		return refuse("expired")
	payload, _, signature = state.rpartition(".")
	if not payload or not hmac.compare_digest(signature, _state_signature(payload.encode())):
		return refuse("expired")
	if int(cookie.get("issued", 0)) < time.time() - STATE_MAX_AGE:
		return refuse("expired")
	_, provider_key, _, _, _, _ = _config()
	if not provider_key:
		return refuse("unavailable")
	try:
		from erpnext.erp_integrations.pramaan import get_client
		claims = get_client().exchange_social_sign_in(
			provider_key=provider_key, code=code, redirect_uri=_redirect_uri(),
			pkce_verifier=cookie.get("verifier") or None,
			expected_nonce=cookie.get("nonce") or None,
		)
	except PramaanError:
		return refuse("rejected")
	user = frappe.db.get_value("User", {"enabled": 1, "email": claims["email"]})
	if not user:
		return refuse("unknown")
	frappe.local.login_manager.login_as(user)
	frappe.local.cookie_manager.delete_cookie(STATE_COOKIE)
	frappe.local.flags.redirect_location = landing
	raise frappe.Redirect
