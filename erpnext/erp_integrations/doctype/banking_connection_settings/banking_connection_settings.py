# Copyright (c) 2026, Pramaan OSS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.doctype.tag.tag import add_tag
from frappe.model.document import Document
from frappe.model.naming import append_number_if_name_exists
from frappe.utils import cint, sbool

from erpnext.erp_integrations.pramaan import get_client
from erpnext.erp_integrations.pramaan import banking as banking_contract


class BankingConnectionSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		automatic_sync: DF.Check
		default_country: DF.Data | None
		enabled: DF.Check
	# end: auto-generated types


def _country(country: str | None) -> str:
	country = (country or frappe.db.get_single_value("Banking Connection Settings", "default_country") or "").strip().upper()
	if len(country) != 2:
		frappe.throw(_("Choose a two-letter bank country first."))
	return country


@frappe.whitelist(methods=["POST"])
def search_institutions(country: str, query: str | None = None):
	frappe.has_permission("Banking Connection Settings", throw=True)
	client = get_client()
	result = client.call("banking.institutions.search", banking_contract.institution_search_request(_country(country), query))
	return banking_contract.institution_rows(result)


@frappe.whitelist(methods=["POST"])
def get_connection_link(country: str, institution_ref: str | None = None):
	"""Start a bank consent and send the person to the hosted connection page."""
	frappe.has_permission("Banking Connection Settings", throw=True)
	return_url = frappe.utils.get_url("/app/banking-connection-settings?bank_return=1")
	body = banking_contract.connection_start_request(
		country=_country(country),
		end_user_ref=frappe.session.user,
		return_url=return_url,
		institution_ref=institution_ref or None,
	)
	client = get_client()
	return client.call("banking.connection.start", body, idempotency_key=client.new_idempotency_key())


@frappe.whitelist(methods=["POST"])
def complete_connection(ref: str, institution_name: str, company: str):
	"""Verify a returned consent, store it on the Bank, and add its accounts."""
	frappe.has_permission("Banking Connection Settings", throw=True)
	client = get_client()
	status = client.call("banking.connection.status", {"ref": ref, "endUserRef": frappe.session.user})
	if status.get("status") not in {"active", "authorized", "connected"}:
		frappe.throw(_("The bank connection has not been authorized yet."))

	bank = ensure_bank(institution_name, ref)
	add_bank_accounts(client, ref, bank, company)
	return bank.name


def ensure_bank(institution_name: str, ref: str) -> object:
	if frappe.db.exists("Bank", institution_name):
		bank = frappe.get_doc("Bank", institution_name)
	else:
		bank = frappe.get_doc({"doctype": "Bank", "bank_name": institution_name})
	bank.bank_connection_ref = ref
	bank.save()
	return bank


def add_bank_accounts(client, ref: str, bank, company: str) -> list[str]:
	parent_gl_account = frappe.get_all(
		"Account", {"company": company, "account_type": "Bank", "is_group": 1, "disabled": 0}
	)
	if not parent_gl_account:
		frappe.throw(
			_("Please set up and enable a group account with the Account Type - {0} for the company {1}").format(
				frappe.bold(_("Bank")), company
			)
		)

	result = []
	for row in client.call("banking.accounts.list", {"ref": ref}).get("accounts") or []:
		account = banking_contract.account_row(row)
		if not account["row_ref"]:
			continue
		acc_type = frappe.db.get_value("Bank Account Type", account["type"])
		if not acc_type and account["type"]:
			add_account_type(account["type"])

		existing = get_existing_bank_account(account["row_ref"], account["name"], company)
		if existing:
			doc = frappe.get_doc("Bank Account", existing)
			doc.update(
				{
					"bank": bank.name,
					"account_name": account["name"],
					"account_type": account["type"],
					"mask": account["masked_number"],
					"integration_id": account["row_ref"],
				}
			)
			doc.save()
			result.append(doc.name)
			continue

		frappe.db.savepoint("banking_bank_account")
		try:
			gl_account = frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": f"{account['name']} - {bank.bank_name}",
					"parent_account": parent_gl_account[0].name,
					"account_type": "Bank",
					"company": company,
				}
			)
			gl_account.insert(ignore_if_duplicate=True)
			new_account = frappe.get_doc(
				{
					"doctype": "Bank Account",
					"bank": bank.name,
					"account": gl_account.name,
					"account_name": account["name"],
					"account_type": account["type"],
					"mask": account["masked_number"],
					"integration_id": account["row_ref"],
					"is_company_account": 1,
					"company": company,
				}
			)
			new_account.insert(set_name=append_number_if_name_exists("Bank Account", f"{account['name']} - {bank.bank_name}"))
			result.append(new_account.name)
		except frappe.UniqueValidationError:
			frappe.db.rollback(save_point="banking_bank_account")
			frappe.msgprint(_("Bank account {0} already exists and could not be created again").format(account["name"]))
		except Exception:
			frappe.db.rollback(save_point="banking_bank_account")
			frappe.log_error("Bank account could not be linked")

	return result


def get_existing_bank_account(integration_id: str, bank_account_name: str, company: str) -> str | None:
	"""Return the company's Bank Account already linked to this platform account, or one with the same name."""
	return frappe.db.get_value(
		"Bank Account", {"integration_id": integration_id, "company": company}
	) or frappe.db.get_value(
		"Bank Account", {"name": bank_account_name, "is_company_account": 1, "company": company}
	)


def add_account_type(account_type):
	try:
		frappe.get_doc({"doctype": "Bank Account Type", "account_type": account_type}).insert()
	except Exception:
		frappe.log_error("Bank account type could not be added")


@frappe.whitelist(methods=["POST"])
def sync_transactions(bank: str, bank_account: str = ""):
	"""Pull new transaction rows through the cursor, for one account or a bank."""
	ref = frappe.db.get_value("Bank", bank, "bank_connection_ref")
	if not ref:
		return

	accounts = (
		[bank_account]
		if bank_account
		else frappe.get_all(
			"Bank Account",
			filters={"bank": bank, "integration_id": ["is", "set"], "disabled": 0},
			pluck="name",
		)
	)
	for account in accounts:
		_sync_account(ref, bank, account)


def _sync_account(ref: str, bank: str, bank_account: str):
	client = get_client()
	account_ref = frappe.db.get_value("Bank Account", bank_account, "integration_id") or bank_account
	cursor = frappe.db.get_value("Bank Account", bank_account, "sync_cursor")
	result = []
	try:
		page = client.call("banking.transactions.sync", banking_contract.transactions_sync_request(ref, cursor),
			idempotency_key=client.new_idempotency_key())
		for row in page.get("added") or []:
			frappe.db.savepoint("banking_sync_txn")
			try:
				result += new_bank_transaction(client, account_ref or bank_account, row)
			except Exception:
				frappe.db.rollback(save_point="banking_sync_txn")
				frappe.log_error(
					_("A bank transaction row could not be imported"),
					reference_doctype="Bank Account",
					reference_name=bank_account,
				)
		frappe.db.set_value(
			"Bank Account", bank_account, {"sync_cursor": page.get("nextCursor") or ""}
		)
		if result:
			last_transaction_date = frappe.db.get_value("Bank Transaction", result[-1], "date")
			frappe.db.set_value("Bank Account", bank_account, "last_integration_date", last_transaction_date)
	except Exception:
		frappe.log_error(frappe.get_traceback(), _("Bank transactions sync error"))


def new_bank_transaction(client, account_ref: str, row: dict) -> list[str]:
	result = []
	mapped = banking_contract.transaction_row(account_ref, row)
	if not mapped or not mapped["transaction_id"] or sbool(row.get("pending")):
		return result
	if frappe.db.exists("Bank Transaction", {"transaction_id": mapped["transaction_id"]}):
		return result

	new_transaction = frappe.get_doc({"doctype": "Bank Transaction", **mapped})
	new_transaction.insert()
	new_transaction.submit()
	result.append(new_transaction.name)
	return result


def automatic_synchronization():
	settings = frappe.get_doc("Banking Connection Settings", "Banking Connection Settings")
	if cint(settings.enabled) and cint(settings.automatic_sync):
		enqueue_synchronization()


@frappe.whitelist(methods=["POST"])
def enqueue_synchronization():
	frappe.has_permission("Banking Connection Settings", throw=True)

	accounts = frappe.get_all(
		"Bank Account",
		filters={"integration_id": ["is", "set"], "disabled": 0, "is_company_account": 1},
		fields=["name", "bank"],
	)

	for account in accounts:
		if frappe.db.get_value("Bank", account.bank, "bank_connection_ref"):
			frappe.enqueue(
				"erpnext.erp_integrations.doctype.banking_connection_settings.banking_connection_settings.sync_transactions",
				bank=account.bank,
				bank_account=account.name,
			)
