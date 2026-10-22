"""Authorized Payment Request endpoints; browser inputs never supply amount or service refs."""
import json
import frappe
from erpnext.erp_integrations.pramaan import get_client
from erpnext.erp_integrations.pramaan.transfers import Transfer, request_body
from erpnext.pramaan import PramaanError


@frappe.whitelist(methods=["POST"])
def transfer(docname: str, operation: str = "status", confirmation: str | None = None, bank_country: str | None = None):
    if frappe.session.user == "Guest":
        frappe.throw("Not permitted", frappe.PermissionError)
    doc = frappe.get_doc("Payment Request", docname)
    doc.check_permission("write")
    frappe.db.sql("select name from `tabPayment Request` where name=%s for update", docname)
    doc.reload()
    if doc.docstatus != 1 or doc.payment_request_type != "Inward":
        frappe.throw("Choose a submitted incoming payment request.")
    state = json.loads(doc.bank_transfer_data or "{}")
    def save(value, durable):
        doc.db_set("bank_transfer_data", json.dumps(value))
        if durable:
            frappe.db.commit()
    try:
        body = state.get("body", {})
        if operation in {"create", "confirm"}:
            body = request_body(doc.grand_total, doc.currency, "Payment Request " + doc.name,
                                bank_country or state.get("body", {}).get("bankCountry"))
        flow = Transfer(get_client(), state, save)
        if operation in {"create", "cancel"}:
            if doc.status in {"Paid", "Partially Paid"} and operation == "create":
                frappe.throw("This payment request is already paid.")
            return flow.prepare(body, operation)
        if operation == "confirm":
            if state.get("intent", {}).get("action") == "create" and doc.status in {"Paid", "Partially Paid"}:
                frappe.throw("This payment request has already received a payment. Refresh its status.")
            result = flow.confirm(confirmation, body, frappe.session.user)
        elif operation == "list":
            return flow.listed()
        elif operation == "status":
            result = flow.refresh(body)
        else:
            frappe.throw("Unknown bank transfer action.")
        if result.get("status") == "paid":
            frappe.db.sql("select name from `tabPayment Request` where name=%s for update", docname)
            doc.reload()
            if doc.status != "Paid":
                doc.set_as_paid()
        return result
    except PramaanError as error:
        frappe.throw(str(error))
