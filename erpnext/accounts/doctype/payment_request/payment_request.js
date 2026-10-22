frappe.ui.form.on("Payment Request", {
	setup: function (frm) {
		frm.set_query("payment_account", function () {
			return {
				filters: {
					account_type: "Bank",
					company: frm.doc.company,
					is_group: 0,
				},
			};
		});

		frm.set_query("party_type", function () {
			return {
				query: "erpnext.setup.doctype.party_type.party_type.get_party_type",
			};
		});
	},
});

frappe.ui.form.on("Payment Request", "onload", function (frm, dt, dn) {
	if (frm.doc.reference_doctype) {
		frappe.call({
			method: "erpnext.accounts.doctype.payment_request.payment_request.get_print_format_list",
			args: { ref_doctype: frm.doc.reference_doctype },
			callback: function (r) {
				set_field_options("print_format", r.message["print_format"]);
			},
		});
	}
});

frappe.ui.form.on("Payment Request", "refresh", function (frm) {
	if (frm.doc.status == "Failed") {
		frm.set_intro(__("Failure: {0}", [frm.doc.failed_reason]), "red");
	}

	let sending_email = false;

	if (
		frm.doc.payment_request_type == "Inward" &&
		frm.doc.payment_channel !== "Phone" &&
		!["Initiated", "Paid"].includes(frm.doc.status) &&
		!frm.doc.__islocal &&
		frm.doc.docstatus == 1
	) {
		frm.add_custom_button(__("Resend Payment Email"), function () {
			if (sending_email) {
				frappe.show_alert({ message: __("Sending Email"), indicator: "blue" });
				return;
			}
			sending_email = true;
			frappe.show_alert({ message: __("Sending Email"), indicator: "blue" });
			frm.call("resend_payment_email").then((r) => {
				const msg = !r.exc ? __("Email Sent") : __("Email couldn't be sent.");
				frappe.show_alert({ message: msg, indicator: !r.exc ? "green" : "red" });
				sending_email = false;
			});
		});
	}

	if (
		frm.doc.payment_request_type == "Inward" &&
		frm.doc.payment_link_ref &&
		!["Paid", "Cancelled"].includes(frm.doc.status) &&
		frm.doc.docstatus == 1
	) {
		frm.add_custom_button(__("Check Payment Status"), function () {
			frm.call("check_payment_link_status").then(() => frm.reload_doc());
		}).addClass("btn-secondary");
	}

	if (
		frm.doc.payment_request_type == "Outward" &&
		["Initiated", "Partially Paid"].includes(frm.doc.status)
	) {
		frm.add_custom_button(__("Create Payment Entry"), function () {
			frappe.call({
				method: "erpnext.accounts.doctype.payment_request.payment_request.make_payment_entry",
				args: { docname: frm.doc.name },
				freeze: true,
				callback: function (r) {
					if (!r.exc) {
						var doc = frappe.model.sync(r.message);
						frappe.set_route("Form", r.message.doctype, r.message.name);
					}
				},
			});
		}).addClass("btn-primary");
	}
});

frappe.ui.form.on("Payment Request", "is_a_subscription", function (frm) {
	frm.toggle_reqd("subscription_plans", frm.doc.is_a_subscription);

	if (frm.doc.is_a_subscription && frm.doc.reference_doctype && frm.doc.reference_name) {
		frappe.call({
			method: "erpnext.accounts.doctype.payment_request.payment_request.get_subscription_details",
			args: { reference_doctype: frm.doc.reference_doctype, reference_name: frm.doc.reference_name },
			freeze: true,
			callback: function (data) {
				if (!data.exc) {
					frm.clear_table("subscription_plans");
					$.each(data.message || [], function (i, v) {
						var d = frappe.model.add_child(
							frm.doc,
							"Subscription Plan Detail",
							"subscription_plans"
						);
						d.qty = v.qty;
						d.plan = v.plan;
					});
					frm.refresh_field("subscription_plans");
				}
			},
		});
	}
});

frappe.ui.form.on("Payment Request", "calculate_total_amount_by_selected_rows", function (frm) {
	if (frm.doc.docstatus !== 0) {
		frappe.msgprint(__("Cannot fetch selected rows for submitted Payment Request"));
		return;
	}
	const selected = frm.get_selected()?.payment_reference || [];
	if (!selected.length) {
		frappe.throw(__("No rows selected"));
	}
	let total = 0;
	selected.forEach((name) => {
		const row = frm.doc.payment_reference.find((d) => d.name === name);
		if (row) {
			row.manually_selected = 1;

			total += row.amount;
		}
	});
	frm.doc.payment_reference.forEach((row) => {
		row.auto_selected = 0;
	});
	frm.set_value("grand_total", total);
	frm.refresh_field("grand_total");
	frm.save();
});

// Bank instructions stay in this dialog; service handles never reach the page.
frappe.ui.form.on('Payment Request', {
  refresh(frm) {
    if (frm.doc.docstatus !== 1 || frm.doc.payment_request_type !== 'Inward') return;
    frm.add_custom_button(__('Pay by bank transfer'), async () => {
      const invoke = async (operation, extra = {}) => (await frappe.call({
        method: 'erpnext.erp_integrations.pramaan.bank_transfer.transfer',
        args: {docname: frm.doc.name, operation, ...extra}, freeze: true,
      })).message;
      const dialog = new frappe.ui.Dialog({title: __('Pay by bank transfer'), fields: [
        {fieldname: 'instructions', fieldtype: 'HTML'},
        {fieldname: 'bank_country', fieldtype: 'Data', label: __('Receiving bank country (two-letter code, required for EUR)')},
      ]});
      const render = (data) => {
        const labels = {awaiting_payment: 'Awaiting payment', partially_paid: 'Partially paid', paid: 'Paid', cancelled: 'Cancelled', expired: 'Expired', not_created: 'No bank transfer request yet'};
        const esc = (value) => frappe.utils.escape_html(String(value ?? ''));
        const bankLabels = {holder: 'Account holder', bankName: 'Bank', iban: 'IBAN', bic: 'BIC', country: 'Country', accountNumber: 'Account number', routingNumber: 'Routing number', sortCode: 'Sort code', swiftCode: 'SWIFT code', networks: 'Networks'};
        const rows = Object.entries(data.bank || {}).map(([key, value]) => `<div>${esc(__(bankLabels[key] || key))}: ${esc(value)}</div>`).join('');
        dialog.fields_dict.instructions.$wrapper.html(`<p>${esc(labels[data.status] || 'Check status')}</p><p>${esc(data.amount == null ? '' : data.currency)} </p>${data.reference ? `<p>${__('Quote this reference')}: <strong>${esc(data.reference)}</strong></p>` : ''}${rows}`);
        dialog.set_primary_action(__(data.status === 'not_created' ? 'Create bank transfer request' : 'Refresh status'), () => data.status === 'not_created' ? prepare('create') : refresh());
        if (['awaiting_payment', 'partially_paid'].includes(data.status)) {
          dialog.set_secondary_action_label(__('Cancel transfer request'));
          dialog.set_secondary_action(() => prepare('cancel'));
          dialog.get_secondary_btn().show();
        } else dialog.get_secondary_btn().hide();
      };
      const refresh = async () => render(await invoke('status'));
      const prepare = async (operation) => {
        const estimate = await invoke(operation, {bank_country: dialog.get_value('bank_country')});
        if (!estimate.confirmation) return render(estimate);
        frappe.confirm(__(operation === 'cancel' ? 'Cancel this bank transfer request? Money already received will not be moved.' : 'Create bank instructions for this payment request?'), async () => {
          render(await invoke('confirm', {confirmation: estimate.confirmation, bank_country: dialog.get_value('bank_country')}));
          frm.reload_doc();
        });
      };
      dialog.show();
      await refresh();
    });
  },
});
