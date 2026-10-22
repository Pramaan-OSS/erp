frappe.pages['payments-account'].on_page_load = function(wrapper) {
  const page = frappe.ui.make_app_page({parent: wrapper, title: __('Payments account'), single_column: true});
  frappe.require('/assets/erpnext/js/payment_account.js', () => {
    wrapper.paymentsAccount = new window.PaymentsAccountPanel(page.main[0], {
      api: (method, args = {}) => frappe.xcall('erpnext.erp_integrations.pramaan.payment_account.' + method, args),
    });
  });
};
