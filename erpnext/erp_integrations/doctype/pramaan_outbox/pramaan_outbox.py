# Copyright (c) 2026, Pramaan OSS and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PramaanOutbox(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		capability: DF.Data | None
		communication: DF.Link | None
		error: DF.SmallText | None
		idempotency_key: DF.Data | None
		message_id: DF.Data | None
		payload: DF.Code | None
		requested_by: DF.Link | None
		result_ref: DF.Data | None
		state: DF.Literal["Pending", "Sending", "Accepted", "Failed", "Uncertain"]
	# end: auto-generated types
