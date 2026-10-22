# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import json
import re
import sys
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_days, nowdate

from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from erpnext.accounts.doctype.payment_entry.test_payment_entry import create_payment_terms_template
from erpnext.accounts.doctype.payment_request.payment_request import (
	get_subscription_details,
	make_payment_request,
)
from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice
from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
from erpnext.accounts.doctype.subscription.test_subscription import (
	create_plan,
	create_subscription,
	make_plans,
)
from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order
from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order
from erpnext.setup.utils import get_exchange_rate
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.tests.utils import ERPTestSuite

PAYMENT_URL = "https://pay.example.com/link"
SEND_EMAIL_MOCK = MagicMock(return_value=None)


def _fake_payments_client():
	"""A fake service client answering payment-link calls from fixtures."""

	class FakePayments:
		def __init__(self):
			self.links = []

		def call(self, capability, inputs, **kwargs):
			if capability == "payments.payment-link.create":
				self.links.append(inputs)
				return {"paymentLinkId": "link-1", "status": "active", "paymentUrl": PAYMENT_URL}
			if capability == "payments.payment-link.orders.list":
				return {"items": []}
			raise AssertionError(capability)

	return FakePayments()


@patch(
	"erpnext.accounts.doctype.payment_request.payment_request.PaymentRequest.send_email",
	new=SEND_EMAIL_MOCK,
)
class TestPaymentRequest(ERPTestSuite):
	def setUp(self):
		SEND_EMAIL_MOCK.reset_mock()
		self.send_email = SEND_EMAIL_MOCK

	def test_payment_request_linkings(self):
		so_inr = make_sales_order(currency="INR", do_not_save=True)
		so_inr.disable_rounded_total = 1
		so_inr.save()

		pr = make_payment_request(
			dt="Sales Order",
			dn=so_inr.name,
			recipient_id="saurabh@example.com",
		)

		self.assertEqual(pr.reference_doctype, "Sales Order")
		self.assertEqual(pr.reference_name, so_inr.name)
		self.assertEqual(pr.currency, "INR")

		conversion_rate = get_exchange_rate("USD", "INR")

		si_usd = create_sales_invoice(currency="USD", conversion_rate=conversion_rate)
		pr = make_payment_request(
			dt="Sales Invoice",
			dn=si_usd.name,
			recipient_id="saurabh@example.com",
		)

		self.assertEqual(pr.reference_doctype, "Sales Invoice")
		self.assertEqual(pr.reference_name, si_usd.name)
		self.assertEqual(pr.currency, "USD")

	def test_payment_link_channels(self):
		so = make_sales_order(currency="USD")

		with patch(
			"erpnext.accounts.doctype.payment_request.payment_request.get_client",
			return_value=_fake_payments_client(),
		):
			pr = make_payment_request(
				dt="Sales Order",
				dn=so.name,
				submit_doc=True,
				return_doc=True,
			)
			pr.reload()

			self.assertEqual(pr.payment_channel, "Email")
			self.assertEqual(pr.payment_url, PAYMENT_URL)
			self.assertEqual(pr.payment_link_ref, "link-1")
			pr.cancel()

			pr = make_payment_request(
				dt="Sales Order",
				dn=so.name,
				payment_channel="Phone",
				phone_number="+15550001111",
				submit_doc=True,
				return_doc=True,
			)
			pr.reload()
			self.assertEqual(pr.payment_url, PAYMENT_URL)
			pr.cancel()

	def test_payment_entry_against_purchase_invoice(self):
		si_usd = make_purchase_invoice(
			supplier="_Test Supplier USD",
			debit_to="_Test Payable USD - _TC",
			currency="USD",
			conversion_rate=50,
		)

		pr = make_payment_request(
			dt="Purchase Invoice",
			dn=si_usd.name,
			party_type="Supplier",
			party="_Test Supplier USD",
			recipient_id="user@example.com",
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)

		pr.create_payment_entry()
		pr.load_from_db()

		self.assertEqual(pr.status, "Paid")

	def test_multiple_payment_entry_against_purchase_invoice(self):
		purchase_invoice = make_purchase_invoice(
			supplier="_Test Supplier USD",
			debit_to="_Test Payable USD - _TC",
			currency="USD",
			conversion_rate=50,
		)

		pr = make_payment_request(
			dt="Purchase Invoice",
			party_type="Supplier",
			party="_Test Supplier USD",
			dn=purchase_invoice.name,
			recipient_id="user@example.com",
			mute_email=1,
			return_doc=1,
		)

		pr.grand_total = pr.grand_total / 2

		pr.submit()
		pr.create_payment_entry()

		purchase_invoice.load_from_db()
		self.assertEqual(purchase_invoice.status, "Partly Paid")

		pr = make_payment_request(
			dt="Purchase Invoice",
			party_type="Supplier",
			party="_Test Supplier USD",
			dn=purchase_invoice.name,
			recipient_id="user@example.com",
			mute_email=1,
			return_doc=1,
		)

		pr.save()
		pr.submit()
		pr.create_payment_entry()

		purchase_invoice.load_from_db()
		self.assertEqual(purchase_invoice.status, "Paid")

	def test_payment_entry(self):
		frappe.db.set_value(
			"Company", "_Test Company", "exchange_gain_loss_account", "_Test Exchange Gain/Loss - _TC"
		)
		frappe.db.set_value("Company", "_Test Company", "write_off_account", "_Test Write Off - _TC")
		frappe.db.set_value("Company", "_Test Company", "cost_center", "_Test Cost Center - _TC")

		so_inr = make_sales_order(currency="INR")
		pr = make_payment_request(
			dt="Sales Order",
			dn=so_inr.name,
			recipient_id="saurabh@example.com",
			payment_account="_Test Bank - _TC",
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)
		pe = pr.set_as_paid()

		so_inr = frappe.get_doc("Sales Order", so_inr.name)

		self.assertEqual(so_inr.advance_paid, 1000)

		si_usd = create_sales_invoice(
			customer="_Test Customer USD",
			debit_to="_Test Receivable USD - _TC",
			currency="USD",
			conversion_rate=50,
		)

		pr = make_payment_request(
			dt="Sales Invoice",
			dn=si_usd.name,
			recipient_id="saurabh@example.com",
			payment_account="_Test Bank USD - _TC",
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)

		pe = pr.create_payment_entry(submit=False)
		pe.source_exchange_rate = 50
		pe.target_exchange_rate = 50
		pe.set_amounts()
		pe.insert(ignore_permissions=True)
		pe.submit()

		expected_gle = dict(
			(d[0], d)
			for d in [
				["_Test Receivable USD - _TC", 0, 5000, si_usd.name],
				[pr.payment_account, 5000.0, 0, None],
			]
		)

		gl_entries = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Payment Entry", "voucher_no": pe.name},
			fields=["account", "debit", "credit", "against_voucher"],
			order_by="account asc",
		)

		self.assertTrue(gl_entries)

		for _i, gle in enumerate(gl_entries):
			self.assertEqual(expected_gle[gle.account][0], gle.account)
			self.assertEqual(expected_gle[gle.account][1], gle.debit)
			self.assertEqual(expected_gle[gle.account][2], gle.credit)
			self.assertEqual(expected_gle[gle.account][3], gle.against_voucher)

	def test_status(self):
		si_usd = create_sales_invoice(
			customer="_Test Customer USD",
			debit_to="_Test Receivable USD - _TC",
			currency="USD",
			conversion_rate=50,
		)

		pr = make_payment_request(
			dt="Sales Invoice",
			dn=si_usd.name,
			recipient_id="saurabh@example.com",
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)

		pe = pr.create_payment_entry()
		pr.load_from_db()

		self.assertEqual(pr.status, "Paid")

		pe.cancel()
		pr.load_from_db()

		self.assertEqual(pr.status, "Requested")

	def test_multiple_payment_entries_against_sales_order(self):
		# Make Sales Order, grand_total = 1000
		so = make_sales_order()

		# Payment Request amount = 200
		pr1 = make_payment_request(
			dt="Sales Order", dn=so.name, recipient_id="nabin@example.com", return_doc=1
		)
		pr1.grand_total = 200
		pr1.submit()

		# Make a 2nd Payment Request
		pr2 = make_payment_request(
			dt="Sales Order", dn=so.name, recipient_id="nabin@example.com", return_doc=1
		)

		self.assertEqual(pr2.grand_total, 800)

		# Try to make Payment Request more than SO amount, should give validation
		pr2.grand_total = 900
		self.assertRaises(frappe.ValidationError, pr2.save)

	def test_conversion_on_foreign_currency_accounts(self):
		po_doc = create_purchase_order(supplier="_Test Supplier USD", currency="USD", do_not_submit=1)
		po_doc.conversion_rate = 80
		po_doc.items[0].qty = 1
		po_doc.items[0].rate = 10
		po_doc.save().submit()

		pr = make_payment_request(dt=po_doc.doctype, dn=po_doc.name, recipient_id="nabin@example.com")
		pr = frappe.get_doc(pr).save().submit()

		pe = pr.create_payment_entry(submit=False)
		pe.target_exchange_rate = 80
		pe.paid_amount = 800
		pe.set_amounts()
		pe.insert(ignore_permissions=True)
		pe.submit()
		self.assertEqual(pe.base_paid_amount, 800)
		self.assertEqual(pe.paid_amount, 800)
		self.assertEqual(pe.base_received_amount, 800)
		self.assertEqual(pe.received_amount, 10)

	def test_multiple_payment_if_partially_paid_for_same_currency(self):
		so = make_sales_order(currency="INR", qty=1, rate=1000)

		self.assertEqual(so.advance_payment_status, "Not Requested")

		pr = make_payment_request(
			dt="Sales Order",
			dn=so.name,
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)

		self.assertEqual(pr.grand_total, 1000)
		self.assertEqual(pr.outstanding_amount, pr.grand_total)
		self.assertEqual(pr.party_account_currency, pr.currency)  # INR
		self.assertEqual(pr.status, "Requested")

		so.load_from_db()
		self.assertEqual(so.advance_payment_status, "Requested")

		# to make partial payment
		pe = pr.create_payment_entry(submit=False)
		pe.paid_amount = 200
		pe.references[0].allocated_amount = 200
		pe.submit()

		self.assertEqual(pe.references[0].payment_request, pr.name)

		so.load_from_db()
		self.assertEqual(so.advance_payment_status, "Partially Paid")

		pr.load_from_db()
		self.assertEqual(pr.status, "Partially Paid")
		self.assertEqual(pr.outstanding_amount, 800)
		self.assertEqual(pr.grand_total, 1000)

		self.assertRaisesRegex(
			frappe.exceptions.ValidationError,
			re.compile(r"Payment Request is already created"),
			make_payment_request,
			dt="Sales Order",
			dn=so.name,
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)
		# complete payment
		pe = pr.create_payment_entry()

		self.assertEqual(pe.paid_amount, 800)  # paid amount set from pr's outstanding amount
		self.assertEqual(pe.references[0].allocated_amount, 800)
		self.assertEqual(pe.references[0].outstanding_amount, 0)  # Also for orders it will zero
		self.assertEqual(pe.references[0].payment_request, pr.name)

		so.load_from_db()
		self.assertEqual(so.advance_payment_status, "Fully Paid")

		pr.load_from_db()
		self.assertEqual(pr.status, "Paid")
		self.assertEqual(pr.outstanding_amount, 0)
		self.assertEqual(pr.grand_total, 1000)

		# creating a more payment Request must not allowed
		self.assertRaisesRegex(
			frappe.exceptions.ValidationError,
			re.compile(r"Payment Entry is already created"),
			make_payment_request,
			dt="Sales Order",
			dn=so.name,
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)

	@ERPTestSuite.change_settings(
		"Accounts Settings", {"allow_multi_currency_invoices_against_single_party_account": 1}
	)
	def test_multiple_payment_if_partially_paid_for_multi_currency(self):
		pi = make_purchase_invoice(currency="USD", conversion_rate=50, qty=1, rate=100, do_not_save=1)
		pi.credit_to = "Creditors - _TC"
		pi.submit()

		pr = make_payment_request(
			dt="Purchase Invoice",
			dn=pi.name,
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)

		# 100 USD -> 5000 INR
		self.assertEqual(pr.grand_total, 100)
		self.assertEqual(pr.outstanding_amount, 5000)
		self.assertEqual(pr.currency, "USD")
		self.assertEqual(pr.party_account_currency, "INR")
		self.assertEqual(pr.status, "Initiated")

		self.assertRaisesRegex(
			frappe.exceptions.ValidationError,
			re.compile(r"Payment Request is already created"),
			make_payment_request,
			dt="Purchase Invoice",
			dn=pi.name,
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)

		# to make partial payment
		pe = pr.create_payment_entry(submit=False)
		pe.paid_amount = 2000
		pe.references[0].allocated_amount = 2000
		pe.submit()

		self.assertEqual(pe.references[0].payment_request, pr.name)

		pr.load_from_db()
		self.assertEqual(pr.status, "Partially Paid")
		self.assertEqual(pr.outstanding_amount, 3000)
		self.assertEqual(pr.grand_total, 100)

		# complete payment
		pe = pr.create_payment_entry()
		self.assertEqual(pe.paid_amount, 3000)  # paid amount set from pr's outstanding amount
		self.assertEqual(pe.references[0].allocated_amount, 3000)
		self.assertEqual(pe.references[0].outstanding_amount, 0)  # for Invoices it will zero
		self.assertEqual(pe.references[0].payment_request, pr.name)

		pr.load_from_db()
		self.assertEqual(pr.status, "Paid")
		self.assertEqual(pr.outstanding_amount, 0)
		self.assertEqual(pr.grand_total, 100)

		# creating a more payment Request must not allowed
		self.assertRaisesRegex(
			frappe.exceptions.ValidationError,
			re.compile(r"Payment Entry is already created"),
			make_payment_request,
			dt="Purchase Invoice",
			dn=pi.name,
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)

	def test_single_payment_with_payment_term_for_same_currency(self):
		create_payment_terms_template()

		po = create_purchase_order(do_not_save=1, currency="INR", qty=1, rate=20000)
		po.payment_terms_template = "Test Receivable Template"  # 84.746 and 15.254
		po.save()
		po.submit()

		self.assertEqual(po.advance_payment_status, "Not Initiated")

		pr = make_payment_request(
			dt="Purchase Order",
			dn=po.name,
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)

		self.assertEqual(pr.grand_total, 20000)
		self.assertEqual(pr.outstanding_amount, pr.grand_total)
		self.assertEqual(pr.party_account_currency, pr.currency)  # INR
		self.assertEqual(pr.status, "Initiated")

		po.load_from_db()
		self.assertEqual(po.advance_payment_status, "Initiated")

		pe = pr.create_payment_entry()

		self.assertEqual(len(pe.references), 2)
		self.assertEqual(pe.paid_amount, 20000)

		# check 1st payment term
		self.assertEqual(pe.references[0].allocated_amount, 16949.2)
		self.assertEqual(pe.references[0].payment_request, pr.name)

		# check 2nd payment term
		self.assertEqual(pe.references[1].allocated_amount, 3050.8)
		self.assertEqual(pe.references[1].payment_request, pr.name)

		po.load_from_db()
		self.assertEqual(po.advance_payment_status, "Fully Paid")

		pr.load_from_db()
		self.assertEqual(pr.status, "Paid")
		self.assertEqual(pr.outstanding_amount, 0)
		self.assertEqual(pr.grand_total, 20000)

	@ERPTestSuite.change_settings(
		"Accounts Settings", {"allow_multi_currency_invoices_against_single_party_account": 1}
	)
	def test_single_payment_with_payment_term_for_multi_currency(self):
		create_payment_terms_template()

		si = create_sales_invoice(
			do_not_save=1, currency="USD", debit_to="Debtors - _TC", qty=1, rate=200, conversion_rate=50
		)
		si.payment_terms_template = "Test Receivable Template"  # 84.746 and 15.254
		si.save()
		si.submit()

		pr = make_payment_request(
			dt="Sales Invoice",
			dn=si.name,
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)

		# 200 USD -> 10000 INR
		self.assertEqual(pr.grand_total, 200)
		self.assertEqual(pr.outstanding_amount, 10000)
		self.assertEqual(pr.currency, "USD")
		self.assertEqual(pr.party_account_currency, "INR")
		self.assertEqual(pr.status, "Requested")

		pe = pr.create_payment_entry()
		self.assertEqual(len(pe.references), 2)
		self.assertEqual(pe.paid_amount, 10000)

		# check 1st payment term
		# convert it via dollar and conversion_rate
		self.assertEqual(pe.references[0].allocated_amount, 8474.5)  # multi currency conversion
		self.assertEqual(pe.references[0].payment_request, pr.name)

		# check 2nd payment term
		self.assertEqual(pe.references[1].allocated_amount, 1525.5)  # multi currency conversion
		self.assertEqual(pe.references[1].payment_request, pr.name)

		pr.load_from_db()
		self.assertEqual(pr.status, "Paid")
		self.assertEqual(pr.outstanding_amount, 0)
		self.assertEqual(pr.grand_total, 200)

	def test_payment_cancel_process(self):
		so = make_sales_order(currency="INR", qty=1, rate=1000)
		self.assertEqual(so.advance_payment_status, "Not Requested")

		pr = make_payment_request(
			dt="Sales Order",
			dn=so.name,
			mute_email=1,
			submit_doc=1,
			return_doc=1,
		)

		self.assertEqual(pr.status, "Requested")
		self.assertEqual(pr.grand_total, 1000)
		self.assertEqual(pr.outstanding_amount, pr.grand_total)

		so.load_from_db()
		self.assertEqual(so.advance_payment_status, "Requested")

		pe = pr.create_payment_entry(submit=False)
		pe.paid_amount = 800
		pe.references[0].allocated_amount = 800
		pe.submit()

		self.assertEqual(pe.references[0].payment_request, pr.name)

		so.load_from_db()
		self.assertEqual(so.advance_payment_status, "Partially Paid")

		pr.load_from_db()
		self.assertEqual(pr.status, "Partially Paid")
		self.assertEqual(pr.outstanding_amount, 200)
		self.assertEqual(pr.grand_total, 1000)

		# cancelling PE
		pe.cancel()

		pr.load_from_db()
		self.assertEqual(pr.status, "Requested")
		self.assertEqual(pr.outstanding_amount, 1000)
		self.assertEqual(pr.grand_total, 1000)

		so.load_from_db()
		self.assertEqual(so.advance_payment_status, "Requested")

	def test_partial_paid_invoice_with_payment_request(self):
		si = create_sales_invoice(currency="INR", qty=1, rate=5000)
		si.save()
		si.submit()

		pe = get_payment_entry("Sales Invoice", si.name, bank_account="_Test Bank - _TC")
		pe.reference_no = "PAYEE0002"
		pe.reference_date = frappe.utils.nowdate()
		pe.paid_amount = 2500
		pe.references[0].allocated_amount = 2500
		pe.save()
		pe.submit()

		si.load_from_db()
		pr = make_payment_request(dt="Sales Invoice", dn=si.name, mute_email=1)

		self.assertEqual(pr.grand_total, si.outstanding_amount)

	def test_partial_paid_invoice_with_more_payment_entry(self):
		pi = make_purchase_invoice(currency="INR", qty=1, rate=500)
		pi.submit()
		pi_1 = make_purchase_invoice(currency="INR", qty=1, rate=300)
		pi_1.submit()

		pr = make_payment_request(dt="Purchase Invoice", dn=pi.name, mute_email=1, submit_doc=0, return_doc=1)
		pr.grand_total = 200
		pr.submit()
		pr.create_payment_entry()
		pr_1 = make_payment_request(
			dt="Purchase Invoice", dn=pi.name, mute_email=1, submit_doc=0, return_doc=1
		)
		pr_1.grand_total = 200
		pr_1.submit()
		pr_1.create_payment_entry()

		pe = get_payment_entry(dt="Purchase Invoice", dn=pi.name)
		pe.paid_amount = 200
		pe.references[0].reference_doctype = pi.doctype
		pe.references[0].reference_name = pi.name
		pe.references[0].grand_total = pi.grand_total
		pe.references[0].outstanding_amount = pi.outstanding_amount
		pe.references[0].allocated_amount = 100
		pe.append(
			"references",
			{
				"reference_doctype": pi_1.doctype,
				"reference_name": pi_1.name,
				"grand_total": pi_1.grand_total,
				"outstanding_amount": pi_1.outstanding_amount,
				"allocated_amount": 100,
			},
		)

		pr_2 = make_payment_request(dt="Purchase Invoice", dn=pi.name, mute_email=1)
		pi.load_from_db()
		self.assertEqual(pr_2.grand_total, pi.outstanding_amount)

	def test_payment_entry_reference_details_fetched_from_invoice(self):
		pi = make_purchase_invoice(currency="INR", qty=1, rate=94500)
		pi.submit()

		pr = make_payment_request(dt="Purchase Invoice", dn=pi.name, mute_email=1, submit_doc=0, return_doc=1)
		pr.grand_total = 94000
		pr.submit()

		pe = pr.create_payment_entry(submit=False)

		self.assertEqual(pe.references[0].reference_name, pi.name)
		self.assertEqual(pe.references[0].total_amount, pi.grand_total)
		self.assertEqual(pe.references[0].outstanding_amount, pi.outstanding_amount)
		self.assertEqual(pe.references[0].allocated_amount, 94000)
		self.assertEqual(pe.paid_amount, 94000)

	def test_consider_journal_entry_and_return_invoice(self):
		from erpnext.accounts.doctype.journal_entry.test_journal_entry import make_journal_entry

		si = create_sales_invoice(currency="INR", qty=5, rate=500)

		je = make_journal_entry("_Test Cash - _TC", "Debtors - _TC", 500, save=False)
		je.accounts[1].party_type = "Customer"
		je.accounts[1].party = si.customer
		je.accounts[1].reference_type = "Sales Invoice"
		je.accounts[1].reference_name = si.name
		je.accounts[1].credit_in_account_currency = 500
		je.submit()

		pe = get_payment_entry("Sales Invoice", si.name)
		pe.paid_amount = 500
		pe.references[0].allocated_amount = 500
		pe.save()
		pe.submit()

		cr_note = create_sales_invoice(qty=-1, rate=500, is_return=1, return_against=si.name, do_not_save=1)
		cr_note.update_outstanding_for_self = 0
		cr_note.save()
		cr_note.submit()

		si.load_from_db()
		pr = make_payment_request(dt="Sales Invoice", dn=si.name, mute_email=1)
		self.assertEqual(pr.grand_total, si.outstanding_amount)

	def test_partial_paid_invoice_with_submitted_payment_entry(self):
		pi = make_purchase_invoice(currency="INR", qty=1, rate=5000)
		pi.save()
		pi.submit()

		pe = get_payment_entry("Purchase Invoice", pi.name, bank_account="_Test Bank - _TC")
		pe.reference_no = "PURINV0001"
		pe.reference_date = frappe.utils.nowdate()
		pe.paid_amount = 2500
		pe.references[0].allocated_amount = 2500
		pe.save()
		pe.submit()
		pe.cancel()

		pe = get_payment_entry("Purchase Invoice", pi.name, bank_account="_Test Bank - _TC")
		pe.reference_no = "PURINV0002"
		pe.reference_date = frappe.utils.nowdate()
		pe.paid_amount = 2500
		pe.references[0].allocated_amount = 2500
		pe.save()
		pe.submit()

		pi.load_from_db()
		pr = make_payment_request(dt="Purchase Invoice", dn=pi.name, mute_email=1)
		self.assertEqual(pr.grand_total, pi.outstanding_amount)

	def test_payment_request_on_unreconcile(self):
		pi = make_purchase_invoice(currency="INR", qty=1, rate=500)
		pi.submit()

		pr = make_payment_request(
			dt=pi.doctype,
			dn=pi.name,
			mute_email=1,
			submit_doc=True,
			return_doc=True,
		)
		self.assertEqual(pr.grand_total, pi.outstanding_amount)

		pe = pr.create_payment_entry()
		unreconcile = frappe.get_doc(
			{
				"doctype": "Unreconcile Payment",
				"company": pe.company,
				"voucher_type": pe.doctype,
				"voucher_no": pe.name,
			}
		)
		unreconcile.add_references()
		unreconcile.submit()

		pi.load_from_db()
		pr.load_from_db()

		self.assertEqual(pr.grand_total, pi.outstanding_amount)

	def test_payment_request_grand_total_from_selected_schedules(self):
		po = create_purchase_order(do_not_save=1, currency="INR", qty=1, rate=100)
		po.payment_schedule = []

		po.append("payment_schedule", {"due_date": nowdate(), "payment_amount": 30})
		po.append("payment_schedule", {"due_date": add_days(nowdate(), 1), "payment_amount": 30})
		po.append("payment_schedule", {"due_date": add_days(nowdate(), 2), "payment_amount": 40})

		po.save()
		po.submit()

		schedules = json.dumps(
			[
				{
					"payment_term": row.payment_term,
					"name": row.name,
					"due_date": row.due_date,
					"payment_amount": row.payment_amount,
					"description": row.description,
				}
				for row in [po.payment_schedule[0], po.payment_schedule[2]]
			]
		)
		pr = make_payment_request(
			dt="Purchase Order",
			dn=po.name,
			mute_email=1,
			submit_doc=False,
			return_doc=True,
			schedules=schedules,
		)

		pr.submit()

		self.assertEqual(pr.grand_total, 70)
		self.assertEqual(len(pr.payment_reference), 2)

	def test_draft_pr_reuse_merges_payment_references(self):
		from frappe.utils import add_days, nowdate

		po = create_purchase_order(do_not_save=1, currency="INR", qty=1, rate=100)
		po.payment_schedule = []
		po.append("payment_schedule", {"due_date": nowdate(), "payment_amount": 50})
		po.append("payment_schedule", {"due_date": add_days(nowdate(), 1), "payment_amount": 50})
		po.save()
		po.submit()
		schedules = json.dumps(
			[
				{
					"payment_term": row.payment_term,
					"name": row.name,
					"due_date": row.due_date,
					"payment_amount": row.payment_amount,
					"description": row.description,
				}
				for row in [po.payment_schedule[0]]
			]
		)
		pr = make_payment_request(
			dt="Purchase Order",
			dn=po.name,
			mute_email=1,
			submit_doc=False,
			return_doc=True,
			schedules=schedules,
		)

		pr.save()
		schedules = json.dumps(
			[
				{
					"payment_term": row.payment_term,
					"name": row.name,
					"due_date": row.due_date,
					"payment_amount": row.payment_amount,
					"description": row.description,
				}
				for row in [po.payment_schedule[1]]
			]
		)
		# call make_payment_request again → reuse draft
		pr_reused = make_payment_request(
			dt="Purchase Order",
			dn=po.name,
			mute_email=1,
			submit_doc=False,
			return_doc=True,
			schedules=schedules,
		)

		self.assertEqual(pr.name, pr_reused.name)
		self.assertEqual(pr_reused.grand_total, 100)
		self.assertEqual(len(pr_reused.payment_reference), 2)

	def test_schedule_pr_not_allowed_if_payment_entry_exists(self):
		po = create_purchase_order(do_not_save=1, currency="INR", qty=1, rate=100)
		po.payment_schedule = []
		row = po.append("payment_schedule", {"due_date": nowdate(), "payment_amount": 100})
		po.save()
		po.submit()

		# create PE first
		pr = make_payment_request(dt="Purchase Order", dn=po.name, mute_email=1, submit_doc=1, return_doc=1)
		pr.create_payment_entry()

		schedules = json.dumps(
			[
				{
					"name": row.name,
					"payment_term": row.payment_term,
					"due_date": row.due_date,
					"payment_amount": row.payment_amount,
					"description": row.description,
				}
			]
		)

		with self.assertRaises(frappe.ValidationError):
			make_payment_request(
				dt="Purchase Order",
				dn=po.name,
				mute_email=1,
				submit_doc=False,
				return_doc=True,
				schedules=schedules,
			)


class TestPaymentRequestPaymentLink(ERPTestSuite):
	def test_payment_link_status_check_marks_paid(self):
		so = make_sales_order(currency="USD")
		pr = make_payment_request(
			dt="Sales Order",
			dn=so.name,
			submit_doc=False,
			return_doc=True,
		)
		pr.payment_link_ref = "link-1"
		pr.submit()

		class FakePaid:
			def call(self, capability, inputs, **kwargs):
				assert capability == "payments.payment-link.orders.list"
				return {"items": [{"orderId": "order-1", "status": "paid", "amount": 1000}]}

		with patch(
			"erpnext.accounts.doctype.payment_request.payment_request.get_client",
			return_value=FakePaid(),
		):
			with patch.object(type(pr), "set_as_paid", return_value=None) as paid:
				pr.check_payment_link_status()
				paid.assert_called_once()

	def test_payment_link_status_without_link_is_refused(self):
		so = make_sales_order(currency="USD")
		pr = make_payment_request(dt="Sales Order", dn=so.name, return_doc=True)
		self.assertRaises(frappe.ValidationError, pr.check_payment_link_status)

	def test_payment_request_with_subscription(self):
		make_plans()

		subscription_plan = frappe.get_doc("Subscription Plan", "_Test Plan Name")

		subscription = create_subscription(
			plans=[{"plan": "_Test Plan Name", "qty": 1}],
			start_date=nowdate(),
			generate_invoice_at="Prepaid (bill at period start)",
			submit_invoice=1,
		)
		invoice_name = frappe.get_value(
			"Sales Invoice",
			{
				"subscription": subscription.name,
				"docstatus": 1,
				"is_return": 0,
			},
			"name",
			order_by="from_date asc",
		)

		payment_request = make_payment_request(
			dt="Sales Invoice",
			dn=invoice_name,
			recipient_id="test@example.com",
		)

		self.assertEqual(payment_request.is_a_subscription, 1)
		self.assertEqual(len(payment_request.subscription_plans), 1)

		subscription_plan = payment_request.subscription_plans[0]
		self.assertEqual(subscription_plan.plan, "_Test Plan Name")
		self.assertEqual(subscription_plan.qty, 1)
		self.assertEqual(payment_request.reference_doctype, "Sales Invoice")
		self.assertEqual(payment_request.reference_name, invoice_name)

	def test_payment_request_without_subscription(self):
		si = create_sales_invoice()
		payment_request = make_payment_request(
			dt="Sales Invoice",
			dn=si.name,
			recipient_id="test@example.com",
		)
		self.assertEqual(payment_request.is_a_subscription, 0)
		self.assertEqual(len(payment_request.subscription_plans), 0)
		self.assertEqual(payment_request.reference_doctype, "Sales Invoice")
		self.assertEqual(payment_request.reference_name, si.name)

	def test_payment_request_with_subscription_for_purchase_invoice(self):
		make_plans()

		subscription_plan = frappe.get_doc("Subscription Plan", "_Test Plan Name")

		subscription = create_subscription(
			party_type="Supplier",
			party="_Test Supplier",
			plans=[{"plan": "_Test Plan Name", "qty": 1}],
			start_date=nowdate(),
			generate_invoice_at="Prepaid (bill at period start)",
			submit_invoice=1,
		)
		invoice_name = frappe.get_value(
			"Purchase Invoice",
			{
				"subscription": subscription.name,
				"docstatus": 1,
				"is_return": 0,
			},
			"name",
			order_by="from_date asc",
		)

		payment_request = make_payment_request(
			dt="Purchase Invoice",
			dn=invoice_name,
			party_type="Supplier",
			party="_Test Supplier",
			recipient_id="test@example.com",
		)

		self.assertEqual(payment_request.is_a_subscription, 1)
		self.assertEqual(len(payment_request.subscription_plans), 1)

		subscription_plan = payment_request.subscription_plans[0]
		self.assertEqual(subscription_plan.plan, "_Test Plan Name")
		self.assertEqual(subscription_plan.qty, 1)
		self.assertEqual(payment_request.reference_doctype, "Purchase Invoice")
		self.assertEqual(payment_request.reference_name, invoice_name)

	def test_payment_request_without_subscription_for_purchase_invoice(self):
		pi = make_purchase_invoice()
		payment_request = make_payment_request(
			dt="Purchase Invoice",
			dn=pi.name,
			party_type="Supplier",
			party=pi.supplier,
			recipient_id="test@example.com",
		)
		self.assertEqual(payment_request.is_a_subscription, 0)
		self.assertEqual(len(payment_request.subscription_plans), 0)
		self.assertEqual(payment_request.reference_doctype, "Purchase Invoice")
		self.assertEqual(payment_request.reference_name, pi.name)

	def test_get_subscription_details_returns_empty_for_doctype_without_subscription_field(self):
		so = make_sales_order()
		self.assertEqual(get_subscription_details("Sales Order", so.name), [])

	def test_get_subscription_details_requires_read_permission_on_reference(self):
		si = create_sales_invoice()

		restricted_user = "no-roles@example.com"
		if not frappe.db.exists("User", restricted_user):
			user = frappe.new_doc("User")
			user.email = restricted_user
			user.first_name = "No Roles"
			user.send_welcome_email = 0
			user.insert()

		accounts_user = "accounts-user@example.com"
		if not frappe.db.exists("User", accounts_user):
			user = frappe.new_doc("User")
			user.email = accounts_user
			user.first_name = "Accounts"
			user.send_welcome_email = 0
			user.add_roles("Accounts User")

		with self.set_user(restricted_user):
			self.assertRaises(frappe.PermissionError, get_subscription_details, "Sales Invoice", si.name)

		with self.set_user(accounts_user):
			self.assertEqual(get_subscription_details("Sales Invoice", si.name), [])
