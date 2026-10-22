"""Payment links through the application's single Pramaan client.

Pure contract mapping lives in module-level functions so review tests can
exercise the platform shapes without the framework; the Payment Request only
consumes the normalized link and order rows.
"""

from erpnext.pramaan import payment_tax_category

MINOR_UNIT_EXCEPTIONS = {"BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3}
MAX_MINOR_UNITS = 99_999_999


def to_minor_units(amount: float, currency: str) -> int:
	exponent = MINOR_UNIT_EXCEPTIONS.get((currency or "").upper(), 2)
	minor = round(float(amount) * (10**exponent))
	if minor < 1 or minor > MAX_MINOR_UNITS:
		raise ValueError("The payment amount is outside the supported range.")
	return int(minor)


def payment_link_request(
	amount: float,
	currency: str,
	*,
	description: str = "",
	reference: str = "",
	customer_name: str = "",
	customer_email: str = "",
	customer_phone: str = "",
	notify_email: bool = False,
	notify_sms: bool = False,
) -> dict:
	body = {
		"amount": to_minor_units(amount, currency),
		"taxCategory": payment_tax_category(),
		"currency": (currency or "").strip().upper(),
		"description": (description or "")[:200],
		"reference": (reference or "")[:100],
	}
	customer = {}
	if customer_name and customer_email:
		customer["name"] = customer_name[:200]
	if customer_email:
		customer["email"] = customer_email
	if customer_phone:
		customer["phone"] = customer_phone[:30]
	if customer:
		body["customer"] = customer
	if notify_email:
		body["notifyEmail"] = True
	if notify_sms:
		body["notifySms"] = True
	return body


def link_from_result(result: dict) -> dict:
	url = result.get("paymentUrl") or ""
	if not url or not result.get("paymentLinkId"):
		raise ValueError("The payment reply holds no usable link.")
	return {"payment_url": url, "payment_link_ref": result["paymentLinkId"]}


def paid_order_amount(result: dict) -> float:
	"""Sum paid order rows; the caller converts units with the link currency."""
	total = 0
	for row in result.get("items") or []:
		if row.get("status") == "paid" and isinstance(row.get("amount"), int):
			total += row["amount"]
	return total
