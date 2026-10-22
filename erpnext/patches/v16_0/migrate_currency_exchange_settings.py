import frappe


def execute():
	# Vendor exchange-rate choices were removed with the single service
	# connection; older sites keep their manual Currency Exchange records.
	frappe.reload_doc("accounts", "doctype", "currency_exchange_settings")
