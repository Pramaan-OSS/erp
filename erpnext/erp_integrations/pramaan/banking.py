"""Bank feeds through the application's single Pramaan client.

Pure contract mapping lives in module-level functions so review tests can
exercise the platform shapes without the framework; frappe wrappers only
persist results into Bank, Bank Account and Bank Transaction records.
"""


def connection_start_request(country: str, end_user_ref: str, return_url: str, institution_ref: str | None = None) -> dict:
	body = {"country": country.strip().upper()[:2], "endUserRef": end_user_ref, "returnUrl": return_url}
	if institution_ref:
		body["institutionRef"] = institution_ref
	return body


def institution_search_request(country: str, query: str | None = None) -> dict:
	body = {"country": country.strip().upper()}
	if query and query.strip():
		body["query"] = query.strip()
	return body


def institution_rows(result: dict) -> list[dict]:
	"""Map the catalogue's owned bank handles into the connection picker."""
	return [{"ref": row["rowRef"], "name": row.get("name") or ""}
		for row in result.get("institutions") or [] if row.get("rowRef")]


def transactions_sync_request(ref: str, cursor: str | None = None, limit: int = 100) -> dict:
	body = {"ref": ref, "limit": max(1, min(int(limit), 100))}
	if cursor:
		body["cursor"] = cursor
	return body


def minor_to_amount(amount: int, currency: str) -> float:
	"""Minor units to a decimal amount; three-decimal currencies included."""
	from decimal import ROUND_HALF_EVEN, Decimal

	exp = {"BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3}.get(
		(currency or "").upper(), 2
	)
	return float(Decimal(int(amount)).scaleb(-exp).quantize(Decimal(1).scaleb(-exp), rounding=ROUND_HALF_EVEN))


def transaction_row(account_row_ref: str, row: dict) -> dict | None:
	"""Map one platform transaction row onto the local Bank Transaction fields."""
	amount = row.get("amount")
	if not isinstance(amount, int):
		return None
	deposit, withdrawal = (abs(amount), 0) if amount >= 0 else (0, abs(amount))
	currency = row.get("currency") or ""
	description = row.get("description") or ""
	counterparty = row.get("counterparty") or {}
	if isinstance(counterparty, dict) and counterparty.get("name"):
		description = description or counterparty["name"]
	reference = row.get("rowRef") or ""
	return {
		"date": (row.get("date") or "")[:10] or None,
		"bank_account": account_row_ref,
		"deposit": minor_to_amount(deposit, currency),
		"withdrawal": minor_to_amount(withdrawal, currency),
		"currency": currency,
		"transaction_id": row.get("rowRef"),
		"reference_number": reference,
		"description": description,
	}


def account_row(row: dict) -> dict:
	return {
		"row_ref": row.get("rowRef") or "",
		"name": row.get("name") or "",
		"type": row.get("type") or "",
		"masked_number": row.get("maskedAccountNumber") or "",
		"currency": row.get("currency") or "",
	}
