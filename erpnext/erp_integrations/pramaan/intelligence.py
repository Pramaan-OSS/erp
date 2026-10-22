"""Data lookups for party, address, tax, shipping and document intake.

Pure contract mapping lives in module-level functions; the frappe wrappers
only read permission-checked records and return normalized suggestions.
Nothing here runs automatically: every call starts from an explicit person
action on a record they can edit, and results are suggestions until saved.
"""
import base64

import frappe
from frappe import _

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


def domain_from_website(website: str) -> str:
	"""Best-effort registrable domain from a party's website field."""
	from urllib.parse import urlparse

	raw = (website or "").strip()
	if not raw:
		return ""
	if "://" not in raw:
		raw = "https://" + raw
	host = urlparse(raw).hostname or ""
	host = host.removeprefix("www.")
	return host.lower()


def company_prefill_request(name: str = "", website: str = "") -> dict:
	body = {}
	if website:
		body["domain"] = domain_from_website(website)
	if name:
		body["name"] = name
	if not body:
		raise ValueError("Enter a name or website to look up.")
	return body


def company_prefill(result: dict) -> dict:
	"""Normalized profile fields a person may accept into Customer/Supplier."""
	location = result.get("location") or ""
	if isinstance(location, dict):
		location = ", ".join(str(location.get(key)) for key in ("city", "region", "country") if location.get(key))
	return {
		"name": result.get("name") or "",
		"domain": result.get("domain") or "",
		"description": result.get("description") or "",
		"industry": result.get("industry") or "",
		"employee_count": result.get("employeeCount"),
		"founded_year": result.get("foundedYear"),
		"location": location,
		"website": result.get("websiteUrl") or "",
	}


def tax_identifier_request(country: str, tax_number: str) -> dict:
	return {"country": (country or "").strip(), "taxNumber": (tax_number or "").strip()}


def tax_identifier_result(kind: str, result: dict) -> dict:
	if kind == "vat":
		return {
			"valid": result.get("valid") is True,
			"name": result.get("companyName") or "",
			"address": result.get("companyAddress") or "",
			"country": result.get("countryCode") or "",
		}
	rows = result.get("registrations") or result.get("results") or []
	first = rows[0] if isinstance(rows, list) and rows else {}
	return {
		"valid": bool(first),
		"name": first.get("name") or first.get("companyName") or "",
		"address": first.get("address") or "",
		"country": first.get("country") or first.get("countryCode") or "",
	}


def geocode_request(address_text: str) -> dict:
	return {"address": (address_text or "").strip()}


def geocode_result(result: dict) -> dict:
	return {
		"display_name": result.get("displayName") or "",
		"latitude": result.get("latitude"),
		"longitude": result.get("longitude"),
	}


def delivery_estimate_request(origin: dict, destination: dict, carrier: str, ship_date: str = "") -> dict:
	def postal_location(value):
		country = (value.get("country") or value.get("countryCode") or "").strip().upper()
		postal_code = (value.get("postalCode") or "").strip()
		if len(country) != 2 or not postal_code:
			raise ValueError("Choose addresses with a two-letter country code and postal code.")
		return {"country": country, "postalCode": postal_code}

	body = {"origin": postal_location(origin), "destination": postal_location(destination), "carrier": carrier}
	if ship_date:
		body["shipDate"] = ship_date
	return body


def delivery_estimate_result(result: dict) -> dict:
	estimates = result.get("estimates") or []
	first = estimates[0] if isinstance(estimates, list) and estimates else {}
	return {
		"earliest": first.get("earliest") or first.get("earliestDeliveryDate") or "",
		"latest": first.get("latest") or first.get("latestDeliveryDate") or "",
	}


def document_attachment_request(file_doc) -> dict:
	"""Read a permission-checked local attachment into a bounded request."""
	file_doc.check_permission("read")
	content = file_doc.get_content()
	if isinstance(content, str):
		content = content.encode()
	if len(content) > MAX_DOCUMENT_BYTES:
		frappe.throw(_("That file is larger than the supported size."))
	extension = (file_doc.file_name or "").rsplit(".", 1)[-1].lower() or "pdf"
	return {
		"content": base64.b64encode(content).decode(),
		"extension": extension,
		"prompt": "Extract the supplier name, invoice number, invoice date, currency and line items with quantities, unit prices and tax amounts.",
	}


def invoice_lines_result(result: dict) -> dict:
	"""Normalized draft lines; every row stays a suggestion until saved."""
	result = result.get("data") if isinstance(result.get("data"), dict) else result
	lines = result.get("lines") or result.get("items") or []
	normalized = []
	for line in lines if isinstance(lines, list) else []:
		normalized.append(
			{
				"item_name": line.get("name") or line.get("description") or line.get("itemName") or "",
				"qty": line.get("quantity") or line.get("qty") or 1,
				"rate": line.get("unitPrice") or line.get("rate") or 0,
				"amount": line.get("amount") or 0,
				"tax_amount": line.get("taxAmount") or line.get("tax") or 0,
			}
		)
	header = result.get("header") or result or {}
	return {
		"supplier": header.get("supplierName") or header.get("supplier") or "",
		"invoice_number": header.get("invoiceNumber") or header.get("number") or "",
		"invoice_date": header.get("invoiceDate") or header.get("date") or "",
		"currency": header.get("currency") or "",
		"lines": normalized,
	}
