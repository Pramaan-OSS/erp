# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CurrencyExchangeSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		disabled: DF.Check
	# end: auto-generated types

	def validate(self):
		# Rates are looked up through the app's single service connection;
		# this screen only decides whether that lookup is allowed at all.
		return
