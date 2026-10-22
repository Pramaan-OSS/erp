// Copyright (c) 2026, Pramaan OSS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Banking Connection Settings", {
	refresh: function (frm) {
		const params = new URLSearchParams(window.location.search);
		let pending = {};
		try {
			pending = JSON.parse(sessionStorage.getItem("erp_bank_connection") || "{}");
		} catch (_) {
			sessionStorage.removeItem("erp_bank_connection");
		}
		const ref = params.get("bank_ref") || (params.has("bank_return") && pending.ref);
		const institution = params.get("bank_name") || "";
		if (ref) {
			window.history.replaceState({}, "", window.location.pathname);
			frappe.prompt(
				[{
					fieldtype: "Data", label: __("Bank name"), fieldname: "bank_name",
					reqd: 1, default: institution,
				}, {
					fieldtype: "Link",
					options: "Company",
					label: __("Company"),
					fieldname: "company",
					reqd: 1,
					default: pending.company || frappe.defaults.get_user_default("Company"),
				}],
				(data) => {
					frappe
						.xcall(
							"erpnext.erp_integrations.doctype.banking_connection_settings.banking_connection_settings.complete_connection",
							{ ref: ref, institution_name: data.bank_name, company: data.company }
						)
						.then(() => {
							sessionStorage.removeItem("erp_bank_connection");
							frappe.show_alert({ message: __("Bank connected"), indicator: "green" });
							frm.reload_doc();
						});
				},
				__("Select a company"),
				__("Continue")
			);
			return;
		}
		if (frm.doc.enabled) {
			frm.add_custom_button(__("Connect a bank"), () => connect_bank(frm));
			frm.add_custom_button(__("Sync Now"), () => {
				frappe.call({
					method:
						"erpnext.erp_integrations.doctype.banking_connection_settings.banking_connection_settings.enqueue_synchronization",
					freeze: true,
					callback: () => {
						const bank_transaction_link = frappe.utils.get_form_link(
							"Bank Transaction",
							"",
							true,
							__("Bank Transactions")
						);
						frappe.msgprint({
							title: __("Sync Started"),
							message: __("The sync has started in the background, please check the {0} list for new records.", [
								bank_transaction_link,
							]),
							alert: 1,
						});
					},
				});
			}).addClass("btn-primary");
		}
	},
});

function connect_bank(frm) {
	frappe.prompt(
		[
			{
				fieldtype: "Data", label: __("Bank Country (two letters)"),
				fieldname: "country", reqd: 1, default: frm.doc.default_country,
			},
			{
				fieldtype: "Link", options: "Company", label: __("Company"),
				fieldname: "company", reqd: 1,
				default: frappe.defaults.get_user_default("Company"),
			},
		],
		(data) => {
			frappe.xcall(
				"erpnext.erp_integrations.doctype.banking_connection_settings.banking_connection_settings.get_connection_link",
				{ country: data.country }
			).then((result) => {
				sessionStorage.setItem("erp_bank_connection", JSON.stringify({ref: result.ref, company: data.company}));
				window.location.href = result.connectUrl;
			}).catch(() => {
				frappe.msgprint({ message: __("Bank feeds are not available yet."), indicator: "orange" });
			});
		},
		__("Connect a bank"),
		__("Continue")
	);
}
