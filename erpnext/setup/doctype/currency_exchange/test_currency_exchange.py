# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
from unittest import mock

import frappe
from frappe.utils import cint, flt

from erpnext.setup.utils import get_exchange_rate
from erpnext.tests.utils import ERPTestSuite


def save_new_records(test_records):
	for record in test_records:
		# If both selling and buying enabled
		purpose = "Selling-Buying"

		if cint(record.get("for_buying")) == 0 and cint(record.get("for_selling")) == 1:
			purpose = "Selling"
		if cint(record.get("for_buying")) == 1 and cint(record.get("for_selling")) == 0:
			purpose = "Buying"
		kwargs = dict(
			doctype=record.get("doctype"),
			docname=record.get("date")
			+ "-"
			+ record.get("from_currency")
			+ "-"
			+ record.get("to_currency")
			+ "-"
			+ purpose,
			fieldname="exchange_rate",
			value=record.get("exchange_rate"),
		)

		try:
			frappe.set_value(**kwargs)
		except frappe.DoesNotExistError:
			curr_exchange = frappe.new_doc(record.get("doctype"))
			curr_exchange.date = record["date"]
			curr_exchange.from_currency = record["from_currency"]
			curr_exchange.to_currency = record["to_currency"]
			curr_exchange.exchange_rate = record["exchange_rate"]
			curr_exchange.for_buying = record["for_buying"]
			curr_exchange.for_selling = record["for_selling"]
			curr_exchange.insert()


test_exchange_values = {"2015-12-15": "66.999", "2016-01-15": "65.1", "2016-01-30": "62.9"}


def fake_rate_client(*args, **kwargs):
	"""A fake service client: dated lookups answer from the fixture table."""

	class FakeRates:
		def call(self, capability, inputs, **kwargs):
			if capability == "finance.exchange-rate.history":
				date = inputs["startDate"]
				if date in test_exchange_values:
					return {"rates": [{"date": date, "rate": float(test_exchange_values[date])}]}
				return {"rates": []}
			if capability == "finance.exchange-rate.get":
				return {"rate": 60.0, "inverseRate": 1 / 60.0}
			raise AssertionError(capability)

	return FakeRates()


@mock.patch(
	"erpnext.erp_integrations.pramaan.get_client", side_effect=fake_rate_client
)
class TestCurrencyExchange(ERPTestSuite):
	def setUp(self):
		self.load_test_records("Currency Exchange")
		save_new_records(self.globalTestRecords["Currency Exchange"])

	def clear_cache(self):
		cache = frappe.cache()
		for date in test_exchange_values.keys():
			key = "currency_exchange_rate_{}:{}:{}".format(date, "USD", "INR")
			cache.delete(key)

	def test_exchange_rate(self, mock_client):
		frappe.db.set_single_value("Accounts Settings", "allow_stale", 1)

		# Start with allow_stale is True
		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-01", "for_buying")
		self.assertEqual(flt(exchange_rate, 3), 60.0)

		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-15", "for_buying")
		self.assertEqual(exchange_rate, 65.1)

		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-30", "for_selling")
		self.assertEqual(exchange_rate, 62.9)

		# Exchange rate as on 15th Dec, 2015
		self.clear_cache()
		exchange_rate = get_exchange_rate("USD", "INR", "2015-12-15", "for_selling")
		self.assertNotEqual(exchange_rate, 60)
		self.assertEqual(flt(exchange_rate, 3), 66.999)

	def test_exchange_rate_never_reads_a_service_setting(self, mock_client):
		settings = frappe.get_single("Currency Exchange Settings")
		self.assertFalse(settings.get("service_provider"))
		self.assertFalse(settings.get("api_endpoint"))

	def test_exchange_rate_strict(self, mock_client):
		# strict currency settings
		frappe.db.set_single_value("Accounts Settings", "allow_stale", 0)
		frappe.db.set_single_value("Accounts Settings", "stale_days", 1)

		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-01", "for_buying")
		self.assertEqual(exchange_rate, 60.0)

		self.clear_cache()
		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-15", "for_buying")
		self.assertEqual(flt(exchange_rate, 3), 65.100)

		exchange_rate = get_exchange_rate("USD", "INR", "2016-01-30", "for_selling")
		self.assertEqual(exchange_rate, 62.9)

		# Exchange rate as on 15th Dec, 2015
		self.clear_cache()
		exchange_rate = get_exchange_rate("USD", "INR", "2015-12-15", "for_buying")
		self.assertEqual(flt(exchange_rate, 3), 66.999)
