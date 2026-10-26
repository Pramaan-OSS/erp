frappe.ui.form.on("Company", {
	refresh(frm) {
		if (frm.is_new() || !["Italy", "Italia", "Italian Republic", "Repubblica Italiana"].includes(frm.doc.country) || !frappe.user.has_role("System Manager")) return;
		frm.add_custom_button(__("Italian invoicing account"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Italian invoicing account"),
				fields: [
					{ fieldtype: "HTML", options: "<p>Use your existing connected invoicing account. Enter its connection handle, never its token. Not yet live-verified.</p>" },
					{ fieldname: "connection", fieldtype: "Data", label: __("Connected account handle"), reqd: 1 },
				],
				primary_action_label: __("Save account"),
				async primary_action(values) {
					try { await frappe.call({ method: "erpnext.erp_integrations.pramaan.italy_einvoice.configure", args: { company: frm.doc.name, connection: values.connection } }); }
					catch { return; } // The framework displays the safe server error.
					dialog.hide();
					frappe.show_alert(__("Invoicing account saved"));
					frm.reload_doc();
				},
			});
			dialog.$wrapper.css("z-index", 2000);
			dialog.show();
		});
	},
});
