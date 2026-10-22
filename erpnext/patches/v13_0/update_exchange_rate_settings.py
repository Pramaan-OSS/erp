import frappe


def execute():
	frappe.reload_doc("accounts", "doctype", "currency_exchange_settings")
