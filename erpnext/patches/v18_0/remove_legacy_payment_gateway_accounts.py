import click
import frappe


def execute():
	doctypes = ["Payment Gateway Account"]
	for doctype in doctypes:
		frappe.delete_doc("DocType", doctype, ignore_missing=True)

	click.secho("Removed the payment-link provider's account screen from this template", fg="yellow")
