import frappe


def execute():
	try:
		from erpnext.patches.v16_0.migrate_currency_exchange_settings import execute

		execute()
	except ImportError:
		# Older sites keep their manual Currency Exchange records.
		frappe.reload_doc("accounts", "doctype", "currency_exchange_settings")
