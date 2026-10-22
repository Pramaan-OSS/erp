"""India e-invoicing through the application's single Pramaan client.

Sales invoices whose company is registered in India can be registered,
read, cancelled and QR-fetched via the platform's GST capabilities. The
taxpayer consent is created once per GSTIN and only its reference is
stored; portal credentials are forwarded once by the platform and never
persisted here.

Pure mapping lives at module level so review tests can exercise the legal
invoice shape without the framework.
"""

# Standard GST state codes by state name, used to fill the legal
# `stateCode` fields from a stored address's state text.
STATE_CODES = {
	"andaman and nicobar islands": "35",
	"andhra pradesh": "37",
	"arunachal pradesh": "12",
	"assam": "18",
	"bihar": "10",
	"chandigarh": "04",
	"chhattisgarh": "22",
	"dadra and nagar haveli and daman and diu": "26",
	"delhi": "07",
	"goa": "30",
	"gujarat": "24",
	"haryana": "06",
	"himachal pradesh": "02",
	"jammu and kashmir": "01",
	"jharkhand": "20",
	"karnataka": "29",
	"kerala": "32",
	"ladakh": "38",
	"lakshadweep": "31",
	"madhya pradesh": "23",
	"maharashtra": "27",
	"manipur": "14",
	"meghalaya": "17",
	"mizoram": "15",
	"nagaland": "13",
	"odisha": "21",
	"puducherry": "34",
	"punjab": "03",
	"rajasthan": "08",
	"sikkim": "11",
	"tamil nadu": "33",
	"telangana": "36",
	"tripura": "16",
	"uttar pradesh": "09",
	"uttarakhand": "05",
	"west bengal": "19",
}

CANCEL_REASONS = {"1", "2", "3", "4"}

EINVOICE_SERVICES = ["einvoice"]


def state_code(state: str) -> str:
	return STATE_CODES.get((state or "").strip().lower(), "")


def consent_request(gstin: str, username: str, username_password: str) -> dict:
	"""One consent request for the e-invoice service.

	The portal credential is forwarded once so the platform can verify it;
	it is not stored or logged by the API and never appears in a result.
	"""
	gstin = (gstin or "").strip().upper()
	username = (username or "").strip()
	if not gstin or not username or not username_password:
		raise ValueError("Enter the GSTIN, the portal username and its password.")
	return {
		"gstin": gstin,
		"username": username,
		"services": EINVOICE_SERVICES,
		"einvoiceCredentials": {"username": username, "password": username_password},
	}


def consent_ref(result: dict) -> str:
	ref = result.get("ref") or ""
	if not ref:
		raise ValueError("The consent reply holds no reference.")
	return ref


def _legal_address(address: dict, *, gstin: str, legal_name: str, allow_unregistered: bool = False) -> dict:
	address_line1 = address.get("address_line1") or ""
	place = address.get("city") or ""
	postal_code = address.get("pincode") or ""
	state = state_code(address.get("state") or "")
	gstin = (gstin or "").strip().upper()
	if not gstin and allow_unregistered:
		# The legal convention for an unregistered buyer.
		gstin = "URP"
	if not (gstin and legal_name and address_line1 and place and postal_code and state):
		raise ValueError(
			"Registering an e-invoice needs the party's tax id (GSTIN) and an address "
			"with line1, city, pincode and a recognized Indian state."
		)
	return {
		"gstin": gstin,
		"legalName": legal_name,
		"addressLine1": address_line1,
		"addressLine2": address.get("address_line2") or "",
		"place": place,
		"postalCode": postal_code,
		"stateCode": state,
	}


def invoice_request(seller: dict, buyer: dict, items: list, totals: dict, document: dict) -> dict:
	"""Build the typed legal invoice.

	`seller`/`buyer` carry gstin, legal_name and address fields (see
	`_legal_address`; an unregistered buyer becomes `URP`); `items` rows carry
	line_number, description, hsn_code, is_service, quantity, unit,
	unit_price, gross_amount, taxable_amount, gst_rate and totals; `totals`
	carries taxable_value, cgst, sgst, igst, cess, round_off, invoice_value;
	`document` carries number and date.
	"""
	for row in items:
		if not row.get("hsn_code"):
			raise ValueError("Every item needs an HSN code before registering an e-invoice.")
		if row.get("gst_rate") is None:
			raise ValueError("Add a GST tax row to the invoice so every item has a GST rate.")
	gst_rate = {row.get("gst_rate") for row in items}
	if len(gst_rate) != 1:
		raise ValueError("All items must share one GST rate for a single-rate e-invoice.")

	seller_state = seller.get("state_code") or state_code(seller.get("state") or "")
	buyer_state = buyer.get("state_code") or state_code(buyer.get("state") or "")
	intra_state = bool(seller_state) and seller_state == buyer_state

	seller_legal = _legal_address(seller, gstin=seller.get("gstin"), legal_name=seller.get("legal_name"))
	buyer_legal = _legal_address(
		buyer, gstin=buyer.get("gstin"), legal_name=buyer.get("legal_name"), allow_unregistered=True
	)
	buyer_legal["placeOfSupply"] = buyer_state or buyer_legal["stateCode"]

	item_rows = []
	for row in items:
		gst = float(row["gst_rate"])
		item = {
			"lineNumber": int(row["line_number"]),
			"isService": bool(row.get("is_service")),
			"hsnCode": str(row["hsn_code"]),
			"description": (row.get("description") or "")[:300],
			"quantity": row.get("quantity"),
			"unit": row.get("unit") or "NOS",
			"unitPrice": float(row["unit_price"]),
			"grossAmount": float(row["gross_amount"]),
			"taxableAmount": float(row["taxable_amount"]),
			"gstRate": gst,
			"totalAmount": float(row["total_amount"]),
		}
		if intra_state:
			half = round(gst / 2, 2)
			item["cgstAmt"] = round(float(row["taxable_amount"]) * half / 100, 2)
			item["sgstAmt"] = round(float(row["taxable_amount"]) * half / 100, 2)
		else:
			item["igstAmt"] = round(float(row["taxable_amount"]) * gst / 100, 2)
		item_rows.append(item)

	invoice_value = totals.get("invoice_value")
	if invoice_value is None:
		raise ValueError("The invoice total is missing.")

	return {
		"version": "1.1",
		"transaction": "Sell",
		"document": {
			"type": "INV",
			"number": str(document.get("number") or ""),
			"date": str(document.get("date") or "")[:10],
		},
		"seller": seller_legal,
		"buyer": buyer_legal,
		"items": item_rows,
		"totals": {
			"taxableValue": float(totals.get("taxable_value") or 0),
			"cgst": float(totals.get("cgst") or 0),
			"sgst": float(totals.get("sgst") or 0),
			"igst": float(totals.get("igst") or 0),
			"cess": float(totals.get("cess") or 0),
			"roundOff": float(totals.get("round_off") or 0),
			"invoiceValue": float(invoice_value),
		},
	}


def registration_result(result: dict) -> dict:
	"""Normalized registration fields stored on the local e-invoice record."""
	irn = result.get("irn") or ""
	if not irn:
		raise ValueError("The registration reply holds no invoice reference number.")
	return {
		"irn": irn,
		"status": result.get("status") or "Registered",
		"acknowledgement_number": str(result.get("acknowledgementNumber") or ""),
		"acknowledged_at": result.get("acknowledgedAt") or "",
		"signed_invoice": result.get("signedInvoice") or "",
		"signed_qr": result.get("signedQr") or "",
		"ewaybill_number": str(result.get("ewaybillNumber") or ""),
		"einvoice_ref": result.get("ref") or "",
	}


def cancel_request(einvoice_ref: str, reason: str, remarks: str) -> dict:
	reason = str(reason or "").strip()
	if reason not in CANCEL_REASONS:
		raise ValueError("Choose a cancellation reason: duplicate, data entry mistake, order cancelled or other.")
	if not (remarks or "").strip():
		raise ValueError("Add cancellation remarks.")
	return {"ref": einvoice_ref, "reason": reason, "remarks": remarks.strip()[:250]}
