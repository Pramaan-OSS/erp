import frappe


def execute():
	# The provider's bank feed was removed; settings moved in this patch no
	# longer exist. The connection flow now runs through the single client.
	frappe.reload_doc("accounts", "doctype", "bank")
