"""Pure FatturaPA request parsing and deterministic offline fixtures."""
import datetime
import hashlib
import math
import os
import re
from xml.etree import ElementTree as ET

NS = 'http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2'
IDS = {'edi.einvoice.submit', 'edi.einvoice.status.get'}


def parse_invoice(xml, account):
    def invalid():
        raise ValueError('The Italian XML is unsupported or incomplete. Correct it before submitting.')
    if not isinstance(xml, str) or len(xml.encode('utf-8')) > 1048576 or re.search(r'<!\s*(DOCTYPE|ENTITY)', xml, re.I):
        invalid()
    if not re.fullmatch(r'conn_[A-Za-z0-9]{1,64}', account or ''):
        raise ValueError('Connect an invoicing account for this company first.')
    try:
        root = ET.fromstring(xml)
        if root.tag != '{' + NS + '}FatturaElettronica':
            invalid()
        # Local-name parsing accepts the template's unqualified children and qualified XML.
        for element in root.iter():
            if element.tag.startswith('{') and not element.tag.startswith('{' + NS + '}'):
                invalid()
            element.tag = element.tag.split('}')[-1]
        bodies = root.findall('FatturaElettronicaBody')
        if len(bodies) != 1 or root.find('.//Signature') is not None:
            invalid()
        body = bodies[0]
        def text(node, path, maximum=1000):
            value = node.findtext(path)
            if not value or not value.strip() or len(value) > maximum:
                invalid()
            return value
        def number(node, path, default=None):
            raw = node.findtext(path)
            value = float(raw) if raw is not None else default
            if value is None or not math.isfinite(value):
                invalid()
            return value
        general = body.find('DatiGenerali/DatiGeneraliDocumento')
        kind = text(general, 'TipoDocumento')
        if kind not in {'TD01', 'TD04'}:
            invalid()
        recipient = root.find('FatturaElettronicaHeader/CessionarioCommittente/DatiAnagrafici')
        vat = recipient.find('IdFiscaleIVA')
        tax = text(vat, 'IdCodice', 32) if vat is not None else text(recipient, 'CodiceFiscale', 32)
        person = recipient.find('Anagrafica')
        name = person.findtext('Denominazione') or ' '.join(filter(None, [person.findtext('Nome'), person.findtext('Cognome')]))
        if not name or len(name) > 300:
            invalid()
        goods = body.find('DatiBeniServizi')
        lines = [{'description': text(line, 'Descrizione'), 'quantity': number(line, 'Quantita', 1),
                  'unitPrice': number(line, 'PrezzoUnitario')} for line in goods.findall('DettaglioLinee')]
        taxes = [{'rate': number(tax, 'AliquotaIVA'), 'amount': number(tax, 'Imposta')}
                 for tax in goods.findall('DatiRiepilogo')]
        if not 1 <= len(lines) <= 1000 or len(taxes) > 100 or any(line['quantity'] <= 0 for line in lines) or any(not 0 <= tax['rate'] <= 100 for tax in taxes):
            invalid()
        date = text(general, 'Data')
        if datetime.date.fromisoformat(date).isoformat() != date:
            invalid()
        currency = text(general, 'Divisa')
        if not re.fullmatch('[A-Z]{3}', currency):
            invalid()
        return {'connectionRef': account, 'country': 'IT', 'documentType': 'invoice' if kind == 'TD01' else 'credit_note',
                'documentNumber': text(general, 'Numero', 100), 'issueDate': date, 'currency': currency,
                'party': {'taxIdentifier': tax, 'name': name}, 'lines': lines, 'taxes': taxes, 'xml': xml}
    except (ET.ParseError, AttributeError, TypeError, OverflowError, ValueError):
        invalid()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fake_response(path, headers, body):
    capability = path.rsplit('/', 1)[-1]
    estimated = capability == 'estimate' and path.rsplit('/', 2)[-2] in IDS
    if capability not in IDS and not estimated:
        return None
    mode = os.environ.get('PRAMAAN_FAKE_EINVOICE', 'pending')
    if mode == 'unavailable':
        return 501, {'error': {'code': 'not_available_yet'}}
    if mode == 'connection_required':
        return 409, {'error': {'code': 'connection_required'}}
    if not headers.get('Pramaan-Account'):
        return 400, {'error': {'code': 'invalid_request'}}
    if estimated:
        return 200, {'can_run': True}
    if mode == 'refused':
        return 400, {'error': {'code': 'invalid_request'}}
    if mode == 'uncertain':
        return 502, {'error': {'code': 'upstream_unavailable'}}
    if capability.endswith('.submit'):
        try:
            if body != parse_invoice(body['xml'], headers['Pramaan-Account']) or not headers.get('Idempotency-Key'):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            return 400, {'error': {'code': 'invalid_request'}}
        return 200, {'ref': 'fixture-invoice-' + digest(headers['Idempotency-Key'])[:20], 'status': 'pending'}
    if not isinstance(body, dict) or set(body) != {'ref'} or not isinstance(body['ref'], str) or not body['ref']:
        return 400, {'error': {'code': 'invalid_request'}}
    status = mode if mode in {'accepted', 'rejected'} else 'accepted' if mode == 'delivery_unavailable' else 'pending'
    result = {'status': status, 'lastCheckedAt': '2026-10-26T12:00:00Z'}
    if status == 'accepted':
        result['receipt'] = 'delivery_unavailable' if mode == 'delivery_unavailable' else 'delivered'
    if status == 'rejected':
        result['rejectionReason'] = 'The exchange rejected this invoice. Review the receipt in your connected account.'
    return 200, result
