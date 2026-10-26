"""Synthetic local records for disposable Italian invoice checks only."""
import uuid
import frappe


def seed(label=None):
    from erpnext.regional.italy.setup import make_custom_fields
    make_custom_fields()
    suffix = label or uuid.uuid4().hex[:8]
    company = 'Italy Fixture ' + suffix
    customer = 'Italy Buyer ' + suffix
    def insert(doctype, name, **values):
        doc = frappe.get_doc({'doctype': doctype, 'name': name, **values})
        doc.db_insert()
        return doc
    insert('Company', company, company_name=company, abbr=suffix[:5], country='Italy', default_currency='EUR',
           tax_id='00000000000', fiscal_code='00000000000', fiscal_regime='RF01', italy_invoicing_connection='conn_Example')
    insert('Customer', customer, customer_name=customer, customer_type='Company', tax_id='11111111111', recipient_code='0000000')
    address = 'Italy Address ' + suffix
    insert('Address', address, address_title='Fixture', address_type='Billing', address_line1='Example Street 1', city='Roma', pincode='00100', country='Italy', country_code='IT')
    invoice = insert('Sales Invoice', 'IT-' + suffix, docstatus=1, company=company, customer=customer,
                     customer_name=customer, company_address=address, customer_address=address, company_tax_id='00000000000',
                     company_fiscal_code='00000000000', company_fiscal_regime='RF01', tax_id='11111111111',
                     posting_date='2026-10-26', currency='EUR', conversion_rate=1, grand_total=30.12,
                     rounded_total=30.12, outstanding_amount=30.12, net_total=24.69, total=24.69,
                     status='Unpaid', is_opening='No', type_of_document='TD01', due_date='2026-11-26')
    item = insert('Sales Invoice Item', 'IT-ITEM-' + suffix, parent=invoice.name, parenttype='Sales Invoice', parentfield='items',
                  idx=1, item_code='Fixture Service', item_name='Fixture Service', description='Example service', qty=2,
                  stock_uom='Nos', rate=12.345, net_rate=12.345, amount=24.69, net_amount=24.69, tax_rate=22, tax_amount=5.43,
                  price_list_rate=0)
    tax = insert('Sales Taxes and Charges', 'IT-TAX-' + suffix, parent=invoice.name, parenttype='Sales Invoice', parentfield='taxes',
                 idx=1, charge_type='On Net Total', rate=22, tax_amount=5.43, total=30.12)
    insert('Item Wise Tax Detail', 'IT-DETAIL-' + suffix, parent=invoice.name, parenttype='Sales Invoice', parentfield='item_wise_tax_details',
           idx=1, item_row=item.name, tax_row=tax.name, rate=22, amount=5.43, taxable_amount=24.69)
    frappe.db.commit()
    return invoice.name, company
