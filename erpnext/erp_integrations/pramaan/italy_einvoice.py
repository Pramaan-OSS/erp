"""Authorized, durable Italian invoice submission. No automatic resend."""
import datetime
import json
import re
import secrets
import uuid

import frappe

from erpnext.erp_integrations.pramaan import get_client
from erpnext.erp_integrations.pramaan.italy_invoice import digest, parse_invoice
from erpnext.pramaan import PramaanError

DOCTYPE = 'Italy Invoice Submission'
OPEN = ['Sending', 'Pending', 'Accepted', 'Rejected', 'Uncertain']


def _invoice(name, write=False):
    if frappe.session.user == 'Guest':
        frappe.throw('Not permitted', frappe.PermissionError)
    doc = frappe.get_doc('Sales Invoice', name)
    doc.check_permission('write' if write else 'read')
    if write:
        doc.check_permission('submit')
    company = frappe.get_doc('Company', doc.company)
    company.check_permission('read')
    if company.country not in {'Italy', 'Italia', 'Italian Republic', 'Repubblica Italiana'} or doc.docstatus != 1:
        frappe.throw('Choose a submitted Italian sales invoice.')
    return doc, company


def protect_connection(doc, method=None):
    if not doc.is_new():
        doc.italy_invoicing_connection = frappe.db.get_value('Company', doc.name, 'italy_invoicing_connection')
    else:
        doc.italy_invoicing_connection = None


@frappe.whitelist(methods=['POST'])
def configure(company: str, connection: str):
    if 'System Manager' not in frappe.get_roles():
        frappe.throw('Only an administrator can configure invoicing.', frappe.PermissionError)
    doc = frappe.get_doc('Company', company)
    doc.check_permission('write')
    if not re.fullmatch(r'conn_[A-Za-z0-9]{1,64}', connection or ''):
        frappe.throw('Enter the connected invoicing account handle.')
    with frappe.cache.lock('italy-company-' + digest(company), timeout=180):
        frappe.db.set_value('Company', company, 'italy_invoicing_connection', connection)
        frappe.db.commit()
    return {'configured': True}


def protect_xml(invoice):
    if frappe.db.exists(DOCTYPE, {'invoice': invoice, 'state': ['in', OPEN]}):
        frappe.throw('This invoice has a recorded submission. Its XML cannot be replaced or removed.')


def protect_file(doc, method=None):
    if doc.attached_to_doctype == 'Sales Invoice' and (doc.file_name or '').lower().endswith('.xml'):
        if method != 'validate' or not doc.is_new():
            protect_xml(doc.attached_to_name)


def _active(invoice):
    names = frappe.get_all(DOCTYPE, filters={'invoice': invoice, 'state': ['in', OPEN]}, pluck='name', limit_page_length=1)
    return frappe.get_doc(DOCTYPE, names[0]) if names else None


def _view(record):
    return {'state': record.state, 'receipt': record.receipt or None,
            'lastCheckedAt': record.last_checked_at or None,
            'message': 'Check the connected account; do not submit again.' if record.state in {'Sending', 'Uncertain'} else
            'The exchange rejected this invoice. Review its receipt in the connected account.' if record.state == 'Rejected' else None}


def _body(doc, company, generate=False):
    from erpnext.regional.italy.utils import get_e_invoice_attachments, prepare_and_attach_invoice
    if generate:
        protect_xml(doc.name)
        file = prepare_and_attach_invoice(doc, replace=True)
    else:
        files = get_e_invoice_attachments(doc) or []
        if len(files) != 1:
            frappe.throw('Generate one Italian XML document before submitting.')
        file = frappe.get_doc('File', files[0].name)
    if not file.is_private or file.attached_to_doctype != 'Sales Invoice' or file.attached_to_name != doc.name:
        frappe.throw('Choose the private XML attached to this invoice.')
    doc._italy_xml_url = file.file_url
    xml = file.get_content()
    if isinstance(xml, bytes):
        xml = xml.decode('utf-8')
    try:
        body = parse_invoice(xml, company.italy_invoicing_connection)
    except ValueError as error:
        frappe.throw(str(error))
    from erpnext.regional.italy.utils import get_unamended_name
    if body['documentNumber'] != get_unamended_name(doc) or body['issueDate'] != str(doc.posting_date) or body['currency'] != doc.currency:
        frappe.throw('The XML does not match this invoice. Generate it again.')
    return body


def _fingerprint(doc, body):
    return digest(frappe.as_json({'modified': str(doc.modified), 'body': body}))


def _save(record, **values):
    record.db_set(values, update_modified=True)
    frappe.db.commit()


@frappe.whitelist(methods=['POST'])
def action(docname: str, operation: str = 'status', confirmation: str | None = None):
    doc, company = _invoice(docname, write=operation in {'prepare', 'confirm'})
    # Also serializes account changes between preview comparison and dispatch.
    with frappe.cache.lock('italy-company-' + digest(company.name), timeout=180):
        with frappe.cache.lock('italy-invoice-' + digest(docname), timeout=180):
            frappe.db.rollback()  # Drop any read snapshot taken before waiting for the lock.
            doc.reload()
            company.reload()
            if doc.company != company.name:
                frappe.throw('The invoice company changed. Open it again before continuing.')
            doc.check_permission('write' if operation in {'prepare', 'confirm'} else 'read')
            record = _active(docname)
            if operation == 'status':
                return _view(record) if record else {'state': 'Not submitted'}
            if operation == 'refresh':
                if not record:
                    return {'state': 'Not submitted'}
                if not record.result_ref:
                    return _view(record)
                try:
                    result = get_client().run('edi.einvoice.status.get', {'ref': record.result_ref}, account=record.account)
                    if result.get('status') not in {'pending', 'accepted', 'rejected'} or not isinstance(result.get('lastCheckedAt'), str):
                        raise PramaanError('invalid_response')
                    checked = datetime.datetime.fromisoformat(result['lastCheckedAt'].replace('Z', '+00:00'))
                    if checked.tzinfo is None:
                        raise PramaanError('invalid_response')
                    receipt = result.get('receipt')
                    if receipt not in {None, 'delivered', 'delivery_unavailable'} or receipt and result['status'] != 'accepted':
                        raise PramaanError('invalid_response')
                    _save(record, state=result['status'].title(), receipt=receipt, last_checked_at=result['lastCheckedAt'])
                except (PramaanError, ValueError):
                    return {**_view(record), 'error': 'Invoice status is not available yet. The last confirmed state is shown.'}
                return _view(record)
            if record:
                return _view(record)
            cache_key = 'italy-confirm-' + digest(frappe.session.user + ':' + docname)
            if operation == 'prepare':
                body = _body(doc, company, generate=True)
                estimate = get_client().estimate('edi.einvoice.submit', body, account=body['connectionRef'])
                if estimate.get('can_run') is not True:
                    frappe.throw('Invoice submission is not available yet. Check the connected account.')
                frappe.db.commit()  # Keep the reviewed private attachment for the next request.
                token = secrets.token_urlsafe(32)
                frappe.cache.set_value(cache_key, {'token': token, 'fingerprint': _fingerprint(doc, body)}, expires_in_sec=600)
                return {'state': 'Confirm', 'confirmation': token, 'xmlUrl': doc._italy_xml_url, 'document': {key: value for key, value in body.items() if key not in {'xml', 'connectionRef'}},
                        'notice': 'Not yet live-verified. Submission is irreversible. Queued is not accepted or delivered.'}
            if operation != 'confirm':
                frappe.throw('Unknown invoice action.')
            intent = frappe.cache.get_value(cache_key) or {}
            body = _body(doc, company)
            if not confirmation or not secrets.compare_digest(str(intent.get('token', '')), str(confirmation)) or intent.get('fingerprint') != _fingerprint(doc, body):
                frappe.throw('The invoice or account changed, or confirmation expired. Review it again.')
            identity = digest(frappe.as_json([company.name, body['documentType'], body['documentNumber'], body['issueDate']]))
            with frappe.cache.lock('italy-identity-' + identity, timeout=180):
                if frappe.db.exists(DOCTYPE, {'reservation': identity}):
                    frappe.throw('This document number has already been attempted. Check its recorded submission.')
                record = frappe.get_doc({'doctype': DOCTYPE, 'invoice': docname, 'company': company.name,
                    'reservation': identity, 'document_identity': identity, 'account': body['connectionRef'],
                    'payload': frappe.as_json({'xmlDigest': digest(body['xml']), 'request': body}), 'idempotency_key': str(uuid.uuid4()),
                    'approved_by': frappe.session.user, 'state': 'Sending'}).insert(ignore_permissions=True)
                snapshot = json.loads(record.payload)
                if snapshot['request'] != body or snapshot['xmlDigest'] != digest(body['xml']):
                    frappe.throw('The private document could not be stored unchanged. Nothing was submitted.')
                frappe.db.commit()  # The durable intent must survive any caller rollback.
                frappe.cache.delete_value(cache_key)
                try:
                    result = get_client().run('edi.einvoice.submit', body, account=record.account,
                        idempotency_key=record.idempotency_key, approved_by=frappe.session.user)
                    if isinstance(result.get('ref'), str) and 0 < len(result['ref']) <= 4096:
                        _save(record, result_ref=result['ref'])
                    if result.get('status') not in {'pending', 'accepted', 'rejected'} or not record.result_ref:
                        raise PramaanError('invalid_response', uncertain=True)
                    _save(record, state=result['status'].title(), result_ref=result['ref'])
                except PramaanError as error:
                    # Only transport-confirmed refusals free the number. Ambiguous failures stay reserved.
                    refused = not error.uncertain and error.code in {'request_rejected', 'forbidden', 'approval_required', 'connection_required', 'not_available_yet', 'missing_api_key'}
                    _save(record, state='Refused' if refused else 'Uncertain', reservation=None if refused else identity)
                    return {**_view(record), 'error': 'Nothing was submitted. Correct the document or account, then review it again.' if refused else 'Submission is uncertain. Check the connected account; do not submit again.'}
                return _view(record)
