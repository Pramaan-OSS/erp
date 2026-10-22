# Pinned-framework compatibility shim.
#
# The vendored framework pin predates frappe.utils.logging; the app's test
# suite calls get_log_db() for two small assertions. This stand-in answers
# those calls against the local Error Log. Standard library only.

import frappe


class LogDB:
	def exists(self, doctype, filters=None):
		return bool(frappe.get_all(doctype, filters=filters or [], limit=1))

	def delete(self, doctype, filters=None):
		for name in frappe.get_all(doctype, filters=filters or [], pluck="name"):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)


def get_log_db():
	return LogDB()
