# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe

from erpnext.templates.pages import help as help_page
from erpnext.tests.utils import ERPTestSuite, change_settings


class TestSupportSettings(ERPTestSuite):
	def test_help_page_respects_default_settings(self):
		with change_settings("Support Settings", get_started_sections=None):
			context = frappe._dict()
			help_page.get_context(context)
			self.assertEqual(context.get_started_sections, [])
			self.assertEqual(context.issues, [])
