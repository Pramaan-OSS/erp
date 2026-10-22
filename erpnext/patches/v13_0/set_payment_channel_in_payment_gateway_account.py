import frappe


def execute():
	# Payment link requests carry their own channel; the removed provider's
	# account doctype no longer exists.
	frappe.reload_doc("accounts", "doctype", "payment_request")
