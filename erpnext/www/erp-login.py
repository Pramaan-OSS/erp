import frappe
from frappe import _

SOCIAL_REASONS = {
	"expired": _("The sign-in request expired. Start again."),
	"cancelled": _("Sign-in was cancelled."),
	"unknown": _("No account matches that sign-in. Ask your administrator to add you."),
	"rejected": _("The sign-in could not be verified. Start again."),
	"unavailable": _("Social sign-in is not set up yet. Use password sign-in."),
}


def get_context(context):
	context.no_cache = 1
	context.social_enabled = bool(frappe.db.get_single_value("Sign-In Settings", "enabled"))
	reason = str(frappe.form_dict.get("social") or "")
	context.social_reason = SOCIAL_REASONS.get(reason, "")
	return context
