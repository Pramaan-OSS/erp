# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


from frappe.model.document import Document


class SupportSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allow_resetting_service_level_agreement: DF.Check
		close_issue_after_days: DF.Int
		get_started_sections: DF.Code | None
		greeting_subtitle: DF.Data | None
		greeting_title: DF.Data | None
		track_service_level_agreement: DF.Check
	# end: auto-generated types

	pass
