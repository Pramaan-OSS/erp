# Copyright (c) 2026, Pramaan OSS and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SignInSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		authorize_url: DF.Data | None
		client_id: DF.Data | None
		enabled: DF.Check
		provider_key: DF.Data | None
		scope: DF.Data | None
		use_pkce: DF.Check
	# end: auto-generated types

	def validate(self):
		if self.authorize_url and not self.authorize_url.startswith("https://"):
			frappe.throw(_("The authorization endpoint must be an https address."))
