import click
import frappe

from erpnext.setup.install import create_gst_custom_fields


def execute():
	# India e-invoicing needs the HSN code on invoice lines; migrated sites
	# get the same custom field fresh installs create.
	create_gst_custom_fields()
	click.secho("Added the GST HSN code field to invoice items", fg="yellow")
