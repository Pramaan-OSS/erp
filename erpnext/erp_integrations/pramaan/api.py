"""Endpoints a person triggers from a record; each is one explicit action.

Every endpoint reads permission-checked records, calls the single client,
and returns suggestions or plain unavailability messages. Nothing writes
unless the person accepts the suggestion in the form afterwards.
"""
import frappe
from frappe import _

from erpnext.erp_integrations.pramaan import get_client
from erpnext.erp_integrations.pramaan import intelligence as contract
from erpnext.pramaan import PramaanError


def _plain(error):
	if isinstance(error, PramaanError) and error.code in {"upstream_unavailable", "not_available_yet"}:
		frappe.msgprint(_("This service is not available yet."))
		return None
	frappe.msgprint(str(error) if isinstance(error, PramaanError) else _("That lookup is not available right now."))
	return None


@frappe.whitelist(methods=["POST"])
def lookup_company(doctype: str, name: str):
	"""Suggest profile details for a Customer or Supplier from its own fields."""
	frappe.only_for(("System Manager", "Accounts User", "Sales User", "Purchase User"))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	website, party_name = doc.get("website") or "", doc.get("name")
	try:
		body = contract.company_prefill_request(name=party_name, website=website)
		result = get_client().call("companies.enrich", body)
	except PramaanError as error:
		return _plain(error)
	except (ValueError, frappe.ValidationError):
		frappe.throw(_("Enter a name or website first."))
	return contract.company_prefill(result)


@frappe.whitelist(methods=["POST"])
def verify_tax_id(doctype: str, name: str, country: str = ""):
	"""Check the party's tax identifier against the official register."""
	frappe.only_for(("System Manager", "Accounts User", "Sales User", "Purchase User"))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	tax_number = doc.get("tax_id") or ""
	if not tax_number:
		frappe.throw(_("Enter a tax id first."))
	client = get_client()
	country = country or doc.get("country") or ""
	try:
		if tax_number[:2].isalpha() and len(tax_number) > 4:
			result = client.call("finance.vat-number.validate", {"vatNumber": tax_number})
			return contract.tax_identifier_result("vat", result)
		result = client.call("companies.tax-identifiers.list",
							 contract.tax_identifier_request(country, tax_number))
		return contract.tax_identifier_result("registry", result)
	except PramaanError as error:
		return _plain(error)


@frappe.whitelist(methods=["POST"])
def geocode_address(address_name: str):
	"""Return checked coordinates for a stored Address."""
	frappe.only_for(("System Manager", "Stock User", "Sales User", "Purchase User"))
	doc = frappe.get_doc("Address", address_name)
	doc.check_permission("read")
	address_text = ", ".join(
		part for part in (
			doc.address_line1, doc.address_line2, doc.city, doc.state,
			doc.pincode, doc.country,
		) if part
	)
	try:
		result = get_client().call("geo.address.geocode", contract.geocode_request(address_text))
	except PramaanError as error:
		return _plain(error)
	return contract.geocode_result(result)


@frappe.whitelist(methods=["POST"])
def delivery_estimate(delivery_note: str, carrier: str):
	"""Estimate the delivery window for a submitted Delivery Note."""
	frappe.only_for(("System Manager", "Stock User", "Sales User"))
	doc = frappe.get_doc("Delivery Note", delivery_note)
	doc.check_permission("read")
	def location(address_name):
		if not address_name:
			frappe.throw(_("Choose the origin and destination addresses first."))
		addr = frappe.get_doc("Address", address_name)
		addr.check_permission("read")
		code = frappe.db.get_value("Country", addr.country, "code") or ""
		return {"country": code.upper(), "postalCode": addr.pincode or ""}

	origin = location(doc.get("dispatch_address_name") or doc.get("company_address"))
	destination = location(doc.get("shipping_address_name") or doc.get("customer_address"))
	try:
		result = get_client().call(
			"shipping.delivery.estimate",
			contract.delivery_estimate_request(origin, destination, carrier, str(doc.posting_date or "")),
		)
	except PramaanError as error:
		return _plain(error)
	return contract.delivery_estimate_result(result)


@frappe.whitelist(methods=["POST"])
def extract_purchase_invoice_lines(attachment_url: str):
	"""Read an attached supplier bill into draft lines; nothing is saved."""
	frappe.only_for(("System Manager", "Accounts User", "Purchase User"))
	file_doc = frappe.get_doc("File", {"file_url": attachment_url})
	try:
		body = contract.document_attachment_request(file_doc)
		result = get_client().call("document.extract", body)
	except PramaanError as error:
		return _plain(error)
	return contract.invoice_lines_result(result)


@frappe.whitelist(methods=["POST"])
def outcome_description(outcome_id: str):
	"""One reviewed outcome's description, without running anything."""
	frappe.only_for("System Manager")
	try:
		return get_client().outcome_get(outcome_id)
	except PramaanError as error:
		return _plain(error)


@frappe.whitelist(methods=["POST"])
def outcome_estimate(outcome_id: str, body: dict | str | None = None):
	"""Steps, worst-case cost and plan for the exact run body; no charge.

	An estimate that needs a connected account comes back as `canRun: false`
	with reason `connection_required` and a slot name; the caller sees a plain
	message naming only the slot.
	"""
	from erpnext.pramaan import connection_requirement

	frappe.only_for("System Manager")
	body = frappe.parse_json(body) if isinstance(body, str) else (body or {})
	try:
		estimate = get_client().outcome_estimate(outcome_id, body)
	except PramaanError as error:
		return _plain(error)
	message = connection_requirement(estimate)
	if message:
		return {"canRun": False, "message": _(message)}
	return estimate


@frappe.whitelist(methods=["POST"])
def outcome_run(outcome_id: str, body: dict | str | None = None, plan: str = "", approve: int = 0):
	"""Run a reviewed body once; requires the estimate's plan and a person's
	explicit approval. The full report comes back for review and is stored
	in the Error Log so nothing about an uncertain run is silently dropped."""
	frappe.only_for("System Manager")
	if not approve:
		frappe.throw(_("Review the estimate and approve the run first."))
	body = frappe.parse_json(body) if isinstance(body, str) else (body or {})
	client = get_client()
	try:
		report = client.outcome_run(
			outcome_id, body, plan=plan or None,
			idempotency_key=client.new_idempotency_key(),
		)
	except PramaanError as error:
		return _plain(error)
	frappe.log_error(
		frappe.as_json(report),
		title=_("Outcome report for {0}").format(outcome_id),
		reference_doctype="Comment",
	)
	return report
