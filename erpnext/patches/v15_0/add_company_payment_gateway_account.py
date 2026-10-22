import frappe


def execute():
	# Payment link requests take their payment account on the request itself;
	# the removed provider's account doctype no longer exists.
	frappe.reload_doc("accounts", "doctype", "payment_request")
