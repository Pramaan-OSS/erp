"""Text messages through the application's single Pramaan client.

Pure helpers live at module level so review tests can exercise the contract
without the framework; each message is one explicit send with its own key.
"""

MAX_BODY = 1600


def send_request(to: str, body: str) -> dict:
	body = (body or "")[:MAX_BODY]
	return {"to": normalize_receiver(to), "body": body}


def normalize_receiver(number: str) -> str:
	"""Best-effort E.164: strip separators, keep one leading plus."""
	number = (number or "").strip()
	if number.startswith("+"):
		return "+" + "".join(ch for ch in number[1:] if ch.isdigit())
	digits = "".join(ch for ch in number if ch.isdigit())
	if not digits:
		raise ValueError("The receiver list holds no usable phone number.")
	return "+" + digits


def send_one(client, to: str, body: str, idempotency_key: str) -> dict:
	return client.call("sms.send", send_request(to, body), idempotency_key=idempotency_key)
