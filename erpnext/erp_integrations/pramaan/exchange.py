"""Currency exchange rates through the application's single Pramaan client.

Pure mapping lives in module-level functions so review tests can exercise the
platform contract without the framework; the frappe wrappers only add cache.
"""

RATE_CACHE_SECONDS = 6 * 3600


def latest_rate_request(from_currency: str, to_currency: str) -> dict:
	return {"from": from_currency.strip().upper(), "to": to_currency.strip().upper()}


def dated_rate_request(from_currency: str, to_currency: str, transaction_date: str) -> dict:
	date = str(transaction_date)[:10]
	return {
		"from": from_currency.strip().upper(),
		"to": to_currency.strip().upper(),
		"startDate": date,
		"endDate": date,
	}


def rate_from_latest(result: dict) -> float:
	rate = result.get("rate")
	if isinstance(rate, (int, float)) and rate > 0:
		return float(rate)
	inverse = result.get("inverseRate")
	if isinstance(inverse, (int, float)) and inverse > 0:
		return 1.0 / float(inverse)
	raise ValueError("The exchange-rate reply holds no usable rate.")


def rate_from_history(result: dict, transaction_date: str) -> float:
	"""Pick the rate of the requested day, else the latest day in the range."""
	rows = [row for row in result.get("rates") or [] if isinstance(row.get("rate"), (int, float))]
	if not rows:
		raise ValueError("The exchange-rate reply holds no usable rate.")
	date = str(transaction_date)[:10]
	exact = [row for row in rows if str(row.get("date", ""))[:10] == date]
	if exact:
		return float(exact[-1]["rate"])
	return float(rows[-1]["rate"])


def fetch_rate(client, from_currency: str, to_currency: str, transaction_date: str | None) -> float:
	"""One shared boundary for both rate capabilities; raises PramaanError."""
	if transaction_date:
		result = client.call("finance.exchange-rate.history",
			dated_rate_request(from_currency, to_currency, transaction_date))
		return rate_from_history(result, transaction_date)
	result = client.call("finance.exchange-rate.get",
		latest_rate_request(from_currency, to_currency))
	return rate_from_latest(result)
