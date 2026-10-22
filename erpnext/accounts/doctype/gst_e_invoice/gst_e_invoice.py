# Copyright (c) 2026, Pramaan OSS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext.erp_integrations.pramaan import get_client
from erpnext.erp_integrations.pramaan import india_gst
from erpnext.pramaan import PramaanError


def flt(value):
	return float(value or 0)


class GSTEInvoice(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		acknowledged_at: DF.Data | None
		acknowledgement_number: DF.Data | None
		cancel_reason: DF.Literal["", "1", "2", "3", "4"]
		cancelled_at: DF.Data | None
		company: DF.Link | None
		consent_ref: DF.Data | None
		customer: DF.Link | None
		einvoice_ref: DF.Data | None
		gstin: DF.Data | None
		idempotency_key: DF.Data | None
		irn: DF.Data | None
		remarks: DF.SmallText | None
		sales_invoice: DF.Link
		signed_invoice: DF.Code | None
		signed_qr: DF.LongText | None
		status: DF.Literal["Consent Needed", "Registered", "Cancelled"]
		ewaybill_number: DF.Data | None
	# end: auto-generated types

	@frappe.whitelist(methods=["POST"])
	def create_consent(self, gstin: str, username: str, username_password: str):
		"""Create the taxpayer consent once; only its reference is stored."""
		try:
			result = get_client().call(
				"india.gst.consent.create",
				india_gst.consent_request(gstin, username, username_password),
				idempotency_key=f"gst-consent::{gstin}::{self.sales_invoice}",
			)
		except PramaanError as error:
			frappe.msgprint(str(error))
			return
		self.gstin = (gstin or "").strip().upper()
		self.consent_ref = india_gst.consent_ref(result)
		self.save()
		frappe.msgprint(_("Taxpayer consent created for {0}.").format(self.gstin))

	@frappe.whitelist(methods=["POST"])
	def register(self):
		"""Register the legal invoice; the person submitting this is the approval."""
		if not (self.consent_ref and self.gstin):
			frappe.throw(_("Create the taxpayer consent first."))
		if self.status == "Registered":
			frappe.throw(_("This invoice is already registered. Check its status instead."))
		invoice = self._legal_invoice()
		if not self.idempotency_key:
			self.idempotency_key = get_client().new_idempotency_key()
			self.save()
		try:
			result = get_client().call(
				"india.gst.einvoice.create",
				{"ref": self.consent_ref, "invoice": invoice},
				idempotency_key=self.idempotency_key,
			)
		except PramaanError as error:
			frappe.msgprint(str(error))
			return
		registration = india_gst.registration_result(result)
		self.db_set(
			{
				"status": "Registered",
				"einvoice_ref": registration["einvoice_ref"] or self.name,
				"irn": registration["irn"],
				"acknowledgement_number": registration["acknowledgement_number"],
				"acknowledged_at": registration["acknowledged_at"],
				"signed_invoice": registration["signed_invoice"] or None,
				"signed_qr": registration["signed_qr"] or None,
				"ewaybill_number": registration["ewaybill_number"] or None,
			}
		)
		frappe.msgprint(
			_("E-invoice registered. Print the QR string on the invoice. IRN {0}.").format(registration["irn"])
		)

	@frappe.whitelist(methods=["POST"])
	def fetch_status(self):
		if not self.einvoice_ref:
			frappe.throw(_("Register the invoice first."))
		try:
			result = get_client().call("india.gst.einvoice.get", {"ref": self.einvoice_ref})
		except PramaanError as error:
			frappe.msgprint(str(error))
			return
		registration = india_gst.registration_result(result)
		self.db_set(
			{
				"status": "Cancelled" if registration["status"] == "Cancelled" else self.status or "Registered",
				"irn": registration["irn"],
				"acknowledgement_number": registration["acknowledgement_number"],
				"acknowledged_at": registration["acknowledged_at"],
				"signed_qr": registration["signed_qr"] or self.signed_qr,
				"ewaybill_number": registration["ewaybill_number"] or None,
				"cancelled_at": result.get("cancelledAt") or self.cancelled_at,
			}
		)
		frappe.msgprint(_("Status checked. IRN {0}.").format(registration["irn"]))

	@frappe.whitelist(methods=["POST"])
	def fetch_qr(self):
		if not self.einvoice_ref:
			frappe.throw(_("Register the invoice first."))
		try:
			result = get_client().call("india.gst.einvoice.qr.get", {"ref": self.einvoice_ref})
		except PramaanError as error:
			frappe.msgprint(str(error))
			return
		signed_qr = result.get("signedQr") or ""
		if not signed_qr:
			frappe.msgprint(_("No QR string was returned yet. Check again later."))
			return
		self.db_set("signed_qr", signed_qr)
		frappe.msgprint(_("QR string updated. Print it on the invoice."))

	@frappe.whitelist(methods=["POST"])
	def cancel(self):
		if self.status != "Registered":
			frappe.throw(_("Only a registered e-invoice can be cancelled."))
		try:
			body = india_gst.cancel_request(self.einvoice_ref, self.cancel_reason, self.remarks)
			result = get_client().call(
				"india.gst.einvoice.cancel", body,
				idempotency_key=f"gst-cancel::{self.name}::{self.irn}",
			)
		except (ValueError, PramaanError) as error:
			frappe.msgprint(str(error))
			return
		self.db_set(
			{
				"status": "Cancelled",
				"cancelled_at": result.get("cancelledAt") or frappe.utils.now_datetime().isoformat(),
			}
		)
		frappe.msgprint(_("E-invoice cancelled."))

	def _legal_invoice(self):
		"""Assemble the typed legal invoice from the submitted Sales Invoice."""
		invoice = frappe.get_doc("Sales Invoice", self.sales_invoice)
		invoice.check_permission("read")
		if invoice.docstatus != 1:
			frappe.throw(_("Only a submitted Sales Invoice can be registered."))
		company = frappe.get_doc("Company", invoice.company)
		if (company.country or "").lower() != "india":
			frappe.throw(_("E-invoicing is wired for India-registered companies."))

		seller_address = (
			frappe.get_doc("Address", company.company_address) if company.get("company_address") else None
		)
		if seller_address is None:
			frappe.throw(_("Set the company's registered address first."))
		buyer_address_name = invoice.customer_address or invoice.shipping_address_name
		if not buyer_address_name or not frappe.db.exists("Address", buyer_address_name):
			frappe.throw(_("Set the customer's address on the invoice first."))
		buyer_address = frappe.get_doc("Address", buyer_address_name)
		customer = frappe.get_doc("Customer", invoice.customer)

		def address_fields(address_doc):
			return {
				"address_line1": address_doc.address_line1 or "",
				"address_line2": address_doc.address_line2 or "",
				"city": address_doc.city or "",
				"pincode": address_doc.pincode or "",
				"state": address_doc.state or "",
			}

		seller = {
			"gstin": self.gstin,
			"legal_name": company.company_name or company.name,
			**address_fields(seller_address),
		}
		buyer = {
			"gstin": (customer.tax_id or "").strip().upper(),
			"legal_name": customer.customer_name or customer.name,
			**address_fields(buyer_address),
		}

		gst_rate = _gst_rate(invoice)
		items = []
		for row in invoice.items:
			items.append(
				{
					"line_number": row.idx,
					"description": row.item_name,
					"hsn_code": row.get("gst_hsn_code") or "",
					"is_service": bool(frappe.db.get_value("Item", row.item_code, "is_stock_item") == 0),
					"quantity": row.qty,
					"unit": row.uom or "NOS",
					"unit_price": row.rate,
					"gross_amount": row.amount,
					"taxable_amount": row.net_amount,
					"gst_rate": gst_rate,
					"total_amount": flt(row.net_amount) * (1 + flt(gst_rate) / 100),
				}
			)

		totals = _gst_totals(invoice)
		if not totals:
			frappe.throw(_("Add GST tax rows (CGST/SGST or IGST) to the invoice first."))

		return india_gst.invoice_request(
			seller, buyer, items, totals,
			{"number": invoice.name, "date": invoice.posting_date},
		)


def _gst_rows(invoice):
	return [
		row
		for row in invoice.get("taxes") or []
		if any(marker in (row.account_head or "").upper() for marker in ("CGST", "SGST", "IGST", "CESS"))
	]


def _gst_rate(invoice):
	rows = _gst_rows(invoice)
	rates = {flt(row.rate) for row in rows}
	if not rates:
		return None
	if len(rates) > 1:
		return max(rates)
	return rates.pop()


def _gst_totals(invoice):
	rows = _gst_rows(invoice)
	if not rows:
		return None
	totals = {
		"taxable_value": flt(invoice.net_total),
		"cgst": 0.0,
		"sgst": 0.0,
		"igst": 0.0,
		"cess": 0.0,
		"round_off": flt(invoice.rounded_total) - flt(invoice.grand_total),
		"invoice_value": flt(invoice.rounded_total) or flt(invoice.grand_total),
	}
	for row in rows:
		head = (row.account_head or "").upper()
		if "CGST" in head:
			totals["cgst"] += flt(row.tax_amount)
		elif "SGST" in head:
			totals["sgst"] += flt(row.tax_amount)
		elif "IGST" in head:
			totals["igst"] += flt(row.tax_amount)
		elif "CESS" in head:
			totals["cess"] += flt(row.tax_amount)
	return totals


@frappe.whitelist()
def open_for_sales_invoice(sales_invoice: str):
	"""Open this invoice's e-invoice record, creating the draft if needed."""
	invoice = frappe.get_doc("Sales Invoice", sales_invoice)
	invoice.check_permission("read")
	existing = frappe.db.get_value("GST E-Invoice", {"sales_invoice": sales_invoice})
	if existing:
		return existing
	record = frappe.new_doc("GST E-Invoice")
	record.sales_invoice = sales_invoice
	record.insert()
	return record.name
