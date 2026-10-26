frappe.ui.form.on("Sales Invoice", {
	refresh: (frm) => {
		if (frm.doc.docstatus == 1) {
			frm.add_custom_button(__("Generate E-Invoice"), () => {
				frm.call({
					method: "erpnext.regional.italy.utils.generate_single_invoice",
					args: {
						docname: frm.doc.name,
					},
					callback: function (r) {
						frm.reload_doc();
						if (r.message) {
							open_url_post(frappe.request.url, {
								cmd: "frappe.core.doctype.file.file.download_file",
								file_url: r.message,
							});
						}
					},
				});
			});
		}
	},
});

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		const call = async (operation, confirmation) => {
			try { return (await frappe.call({
			method: "erpnext.erp_integrations.pramaan.italy_einvoice.action",
			args: { docname: frm.doc.name, operation, confirmation },
			})).message; }
			catch { return null; } // The framework already displays the safe server error.
		};
		const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
		const show = (result) => {
			const statusDialog = new frappe.ui.Dialog({ title: __("Italian e-invoice"), fields: [{ fieldtype: "HTML", options: `<p><strong>${escape(result.state)}</strong></p>${result.receipt ? `<p>Receipt: ${escape(result.receipt === "delivered" ? "Delivered" : "Delivery unavailable")}</p>` : ""}${result.lastCheckedAt ? `<p>Last checked: ${escape(result.lastCheckedAt)}</p>` : ""}<p>${escape(result.error || result.message || "")}</p><p class="text-muted">Not yet live-verified. Exchange acceptance is separate from delivery, recipient acceptance and payment.</p>` }] });
			statusDialog.$wrapper.one("hidden.bs.modal", () => statusDialog.$wrapper.remove());
			statusDialog.$wrapper.css("z-index", 2000);
			statusDialog.show();
		};
		frm.add_custom_button(__("E-invoice status"), async () => { const result = await call("refresh"); if (result) show(result); });
		if (!frm.perm.some((permission) => permission.write && permission.submit)) return;
		frm.add_custom_button(__("Submit Italian e-invoice"), async () => {
			const result = await call("prepare");
			if (!result) return;
			if (result.state !== "Confirm") return show(result);
			const doc = result.document;
			const rows = doc.lines.map((line) => `<tr><td>${escape(line.description)}</td><td>${escape(line.quantity)}</td><td>${escape(line.unitPrice)}</td></tr>`).join("");
			const taxes = doc.taxes.map((tax) => `<p>Tax ${escape(tax.rate)}%: ${escape(tax.amount)} ${escape(doc.currency)}</p>`).join("");
			const dialog = new frappe.ui.Dialog({
				title: __("Confirm Italian e-invoice"), size: "large",
				fields: [{ fieldtype: "HTML", options: `<p>${escape(result.notice)}</p><p>${escape(doc.documentType === "credit_note" ? "Credit note" : "Invoice")} ${escape(doc.documentNumber)} · ${escape(doc.issueDate)} · ${escape(doc.currency)}</p><p>${escape(doc.party.name)} · ${escape(doc.party.taxIdentifier)}</p><div class="table-responsive"><table class="table"><thead><tr><th>Description</th><th>Quantity</th><th>Unit price</th></tr></thead><tbody>${rows}</tbody></table></div>${taxes}<p>These are the amounts in the private XML attached to this invoice. <a href="${escape(result.xmlUrl)}" target="_blank" rel="noopener">Download the complete XML</a> before confirming.</p>` }],
				primary_action_label: __("Confirm submission"),
				async primary_action() {
					dialog.get_primary_btn().prop("disabled", true);
					try {
						const outcome = await call("confirm", result.confirmation);
						if (!outcome) { dialog.hide(); return; }
						dialog.$wrapper.one("hidden.bs.modal", () => show(outcome));
						dialog.hide();
					}
					catch { dialog.hide(); }
				},
			});
			dialog.$wrapper.css("z-index", 2000);
			dialog.show();
		});
	},
});
