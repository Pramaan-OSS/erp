// Copyright (c) 2026, Pramaan OSS and contributors
// For license information, please see license.txt

frappe.ui.form.on("GST E-Invoice", {
	refresh: function (frm) {
		if (frm.doc.__islocal) {
			return;
		}
		if (!frm.doc.consent_ref) {
			frm.add_custom_button(__("Create Taxpayer Consent"), function () {
				frappe.prompt(
					[
						{ fieldtype: "Data", label: __("Seller GSTIN"), fieldname: "gstin", reqd: 1 },
						{ fieldtype: "Data", label: __("GST portal username"), fieldname: "username", reqd: 1 },
						{ fieldtype: "Password", label: __("GST portal password"), fieldname: "username_password", reqd: 1 },
					],
					(data) => {
						frm.call("create_consent", data).then(() => frm.reload_doc());
					},
					__("Taxpayer consent"),
					__("Continue")
				);
			});
		}
		if (frm.doc.consent_ref && frm.doc.status !== "Registered") {
			frm.add_custom_button(__("Register E-Invoice"), function () {
				frm.call("register").then(() => frm.reload_doc());
			}).addClass("btn-primary");
		}
		if (frm.doc.einvoice_ref) {
			frm.add_custom_button(__("Check Status"), function () {
				frm.call("fetch_status").then(() => frm.reload_doc());
			});
			frm.add_custom_button(__("Fetch QR String"), function () {
				frm.call("fetch_qr").then(() => frm.reload_doc());
			});
		}
		if (frm.doc.status === "Registered") {
			frm.add_custom_button(__("Cancel E-Invoice"), function () {
				frappe.prompt(
					[
						{
							fieldtype: "Select",
							label: __("Reason"),
							fieldname: "cancel_reason",
							options: "1\n2\n3\n4",
							description: __("1 duplicate, 2 data entry mistake, 3 order cancelled, 4 other"),
							reqd: 1,
						},
						{ fieldtype: "Small Text", label: __("Remarks"), fieldname: "remarks", reqd: 1 },
					],
					(data) => {
						frm.set_value("cancel_reason", data.cancel_reason);
						frm.set_value("remarks", data.remarks);
						frm.save().then(() => {
							frm.call("cancel").then(() => frm.reload_doc());
						});
					},
					__("Cancel e-invoice"),
					__("Cancel")
				);
			});
		}
		if (frm.doc.signed_qr) {
			frm.dashboard.add_comment(
				frappe.utils.escape_html(frm.doc.signed_qr),
				__("Signed QR string"),
				"blue"
			);
		}
	},
});
