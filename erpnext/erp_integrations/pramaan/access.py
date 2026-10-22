"""Close framework routes that would configure outside services directly."""
import json

import frappe

# The app's own OAuth server stays: these routes authorize local clients.
OWN_OAUTH_PATHS = frozenset({
	"/api/method/frappe.integrations.oauth2.authorize",
	"/api/method/frappe.integrations.oauth2.approve",
	"/api/method/frappe.integrations.oauth2.get_token",
	"/api/method/frappe.integrations.oauth2.openid_profile",
})

RETIRED_MARKERS = ("login_via_", "oauth2_logins", ".telephony.", "telephony.", "frappe.www.login.custom")

# Inherited vendor-configuration screens stay closed for every account.
RESTRICTED_DOCTYPES = frozenset({
	"Email Domain", "Connected App", "Social Login Key", "Server Script", "Webhook",
	"SMS Settings",
})

# Local identity/session records the app owns and administers itself.
LOCAL_AUTH_DOCTYPES = frozenset({
	"OAuth Client", "OAuth Bearer Token", "OAuth Authorization Code", "OAuth Provider Settings",
	"Sign-In Settings",
})


def authenticate():
	# Outside-service entrypoints are blocked for every account, including admins.
	path = f"/api/method/{frappe.form_dict.cmd}" if frappe.form_dict.cmd else frappe.request.path
	if path in OWN_OAUTH_PATHS:
		return
	if path.startswith("/api/method/") and any(marker in path for marker in RETIRED_MARKERS):
		frappe.throw("This connection is not available yet.", frappe.PermissionError)

	doctype = frappe.form_dict.get("doctype") or frappe.form_dict.get("dt")
	if not doctype and (frappe.form_dict.get("doc") or frappe.form_dict.get("docs")):
		try:
			raw_doc = frappe.form_dict.get("doc") or frappe.form_dict.get("docs")
			doc = json.loads(raw_doc) if isinstance(raw_doc, str) else raw_doc
			doctype = doc.get("doctype")
		except (ValueError, AttributeError):
			frappe.throw("Invalid document.")

	if doctype and doctype not in LOCAL_AUTH_DOCTYPES and (
		doctype in RESTRICTED_DOCTYPES
		or frappe.db.get_value("DocType", doctype, "module") == "Integrations"
	):
		frappe.throw("Configure connections in the service settings.", frappe.PermissionError)
