import frappe

import erpnext
from erpnext.tests.utils import ERPTestSuite


@erpnext.allow_regional
def test_method():
	return "original"


class TestInit(ERPTestSuite):
	def test_regional_overrides(self):
		frappe.flags.country = "Maldives"
		self.assertEqual(test_method(), "original")
