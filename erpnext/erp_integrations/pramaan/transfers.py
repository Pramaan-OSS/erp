"""Bank transfers: durable approval, one request per bill, trusted settlement reads."""
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP
from erpnext.pramaan import PramaanError

PREFIX = "payments.transfer-request."
CONNECT = "Connect your payments account first, then try again."
BANK_FIELDS = ("holder", "bankName", "iban", "bic", "country", "accountNumber", "routingNumber", "sortCode", "swiftCode", "networks")
EXPONENTS = {"JPY": 0, "KRW": 0, "VND": 0, "BHD": 3, "JOD": 3, "KWD": 3, "OMR": 3, "TND": 3}


def request_body(amount, currency, description, bank_country=None):
    currency = (currency or "").upper()
    minor = int((Decimal(str(amount)) * 10 ** EXPONENTS.get(currency, 2)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if minor <= 0 or len(currency) != 3 or not currency.isalpha():
        raise PramaanError("invalid_amount")
    body = {"amount": minor, "currency": currency, "description": description[:500]}
    if currency == "EUR":
        country = (bank_country or "").strip().upper()
        if len(country) != 2 or not country.isalpha():
            error = PramaanError("bank_country_required")
            error.args = ("Enter the receiving bank country as a two-letter code.",)
            raise error
        body["bankCountry"] = country
    return body


class Transfer:
    def __init__(self, client, state, save):
        self.client, self.state, self.save = client, state, save

    def view(self, result=None):
        result = result or self.state.get("result", {})
        return {key: result[key] for key in ("status", "amount", "currency", "amountReceived", "reference", "bank", "expiresAt") if key in result}

    def prepare(self, body, action="create"):
        if action not in {"create", "cancel"}:
            raise PramaanError("invalid_action")
        if action == "create" and self.state.get("ref"):
            return self.refresh(body)
        if action == "cancel":
            body = {"ref": self.state.get("ref")}
            if not body["ref"]:
                raise PramaanError("missing_request")
        estimate = self.client.estimate(PREFIX + action, body)
        allowed = estimate.get("can_run", estimate.get("canRun"))
        if allowed is not True:
            error = PramaanError("connection_required" if estimate.get("reason") == "connection_required" else "request_rejected")
            if error.code == "connection_required":
                error.args = (CONNECT,)
            raise error
        intent = self.state.get("intent", {})
        if intent.get("sent") and (intent.get("body") != body or intent.get("action") != action):
            raise PramaanError("approval_changed", uncertain=True)
        # Preserve the original key if a response was lost; never invent a second request.
        key = intent.get("key") if intent.get("body") == body and intent.get("action") == action else str(uuid.uuid4())
        self.state["intent"] = {"body": body, "action": action, "key": key,
                                "token": str(uuid.uuid4()), "expires": time.time() + 600, "sent": intent.get("sent", False)}
        self.save(self.state, True)
        return {"confirmation": self.state["intent"]["token"], "action": action,
                "amount": body.get("amount"), "currency": body.get("currency")}

    def confirm(self, token, body, user):
        intent = self.state.get("intent", {})
        if not token or token != intent.get("token") or intent.get("expires", 0) < time.time():
            raise PramaanError("approval_required")
        action = intent["action"]
        expected = body if action == "create" else {"ref": self.state.get("ref")}
        if intent["body"] != expected:
            raise PramaanError("approval_changed")
        intent["sent"] = True
        self.save(self.state, True)
        result = self.client.call(PREFIX + action, expected, idempotency_key=intent["key"])
        if action == "create":
            if not result.get("ref") or result.get("status") != "awaiting_payment":
                raise PramaanError("invalid_response", uncertain=True)
            self.state["ref"] = result["ref"]
            self.state["body"] = body
            self.state["result"] = {**self.view(result), "bank": {k: v for k, v in (result.get("bank") or {}).items() if k in BANK_FIELDS}}
        # Only get decides paid, including after cancel.
        self.state.pop("intent", None)
        self.save(self.state, False)
        return self.refresh(body)

    def refresh(self, body):
        if not self.state.get("ref"):
            return {"status": "not_created"}
        result = self.client.call(PREFIX + "get", {"ref": self.state["ref"]})
        original = self.state["body"]
        if result.get("amount") != original["amount"] or result.get("currency") != original["currency"] or result.get("status") not in {"awaiting_payment", "partially_paid", "paid", "expired", "cancelled"}:
            raise PramaanError("invalid_response")
        if result["status"] == "paid" and result.get("amountReceived", 0) < original["amount"]:
            raise PramaanError("invalid_response")
        self.state["result"] = {**self.state.get("result", {}), **self.view(result)}
        self.save(self.state, False)
        return self.view()

    def listed(self):
        # Never disclose other invoices from the account-wide list.
        if not self.state.get("ref"):
            return []
        result = self.client.call(PREFIX + "list", {"limit": 50})
        # The live list answers with "results".
        # Rows carry their own handle in ref and the create call's id in createdRef.
        return [self.view(row) for row in result.get("results", []) if self.state.get("ref") in (row.get("createdRef"), row.get("ref"))]
