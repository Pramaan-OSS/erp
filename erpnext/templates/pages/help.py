import json

import frappe


def get_context(context):
	context.no_cache = 1
	settings = frappe.get_doc("Support Settings", "Support Settings")

	# Get Started sections
	sections = json.loads(settings.get_started_sections or "[]")
	context.get_started_sections = sections

	# Issues
	if frappe.session.user != "Guest":
		context.issues = frappe.get_list("Issue", fields=["name", "status", "subject", "modified"])[:3]
	else:
		context.issues = []
