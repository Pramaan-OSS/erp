import frappe
from frappe import _
from frappe.utils import sanitize_html
from frappe.utils.global_search import search
from jinja2 import utils


def get_context(context):
	context.no_cache = 1
	if frappe.form_dict.q:
		query = str(utils.escape(sanitize_html(frappe.form_dict.q)))
		context.title = _("Help Results for")
		context.query = query

		context.route = "/search_help"
		d = frappe._dict()
		d.results_sections = get_help_results_sections(query)
		context.update(d)
	else:
		context.title = _("Help Search")


@frappe.whitelist(allow_guest=True)
def get_help_results_sections(text: str):
	out = []
	raw = search(text, 0, 20, "Help Article")
	results = prepare_results(raw)
	if results:
		out.append({"title": _("Help Articles"), "results": results})
	return out


def prepare_results(raw):
	results = []
	for r in raw:
		prepared_result = {}
		parts = r["content"].split(" ||| ")

		for part in parts:
			pair = part.split(" : ", 1)
			prepared_result[pair[0]] = pair[1]

		results.append(
			frappe._dict(
				{
					"title": prepared_result.get("title", ""),
					"preview": prepared_result.get("content", ""),
					"route": prepared_result.get("route", ""),
				}
			)
		)

	return results[:5]
