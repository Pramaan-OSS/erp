import frappe


def execute():
	# Text messages go through the app's single service connection; the old
	# gateway settings screen is retired and no role seeding is needed.
	frappe.reload_doc("selling", "doctype", "sms_center")
