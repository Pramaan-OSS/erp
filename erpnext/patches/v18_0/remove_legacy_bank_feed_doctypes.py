import click
import frappe


def execute():
	# The provider's bank feed was removed; drop its settings doctype and the
	# secret column it kept on Bank. ignore_missing keeps fresh installs clean.
	frappe.delete_doc("DocType", "Plaid Settings", ignore_missing=True)
	try:
		frappe.db.delete_column("Bank", "plaid_access_token")
	except Exception:
		pass

	click.secho("Removed the retired bank-feed settings from this template", fg="yellow")
