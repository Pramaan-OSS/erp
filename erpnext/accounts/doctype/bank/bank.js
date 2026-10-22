// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bank", {
	refresh: function (frm) {
		add_fields_to_mapping_table(frm);
		frm.toggle_display(["address_html", "contact_html"], !frm.doc.__islocal);

		if (frm.doc.__islocal) {
			frm.set_df_property("address_and_contact", "hidden", 1);
			frappe.contacts.clear_address_and_contact(frm);
		} else {
			frm.set_df_property("address_and_contact", "hidden", 0);
			frappe.contacts.render_address_and_contact(frm);
		}
		if (frm.doc.bank_connection_ref) {
			frm.add_custom_button(__("Sync Transactions"), () => {
				frappe.call({
					method:
						"erpnext.erp_integrations.doctype.banking_connection_settings.banking_connection_settings.sync_transactions",
					args: { bank: frm.doc.name, bank_account: "" },
					freeze: true,
				});
			});
		}
	},
});

let add_fields_to_mapping_table = function (frm) {
	let options = [];

	frappe.model.with_doctype("Bank Transaction", function () {
		let meta = frappe.get_meta("Bank Transaction");
		meta.fields.forEach((value) => {
			if (!["Section Break", "Column Break"].includes(value.fieldtype)) {
				options.push(value.fieldname);
			}
		});
	});

	const grid = frm.fields_dict.bank_transaction_mapping?.grid;

	if (grid) {
		grid.update_docfield_property("bank_transaction_field", "options", options);
	}
};
