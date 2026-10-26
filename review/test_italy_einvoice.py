"""Italian XML and account transport contracts; no network."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from erpnext.erp_integrations.pramaan.italy_invoice import parse_invoice
from erpnext.pramaan import PramaanClient, PramaanError

XML = (Path(__file__).resolve().parents[1] / 'erpnext/tests/fixtures/italy_invoice.xml').read_text()


class ItalyContracts(unittest.TestCase):
    def test_exact_xml_values_and_credit_note_signs(self):
        body = parse_invoice(XML, 'conn_Example')
        self.assertEqual(body['lines'], [{'description': 'Service & support', 'quantity': 2, 'unitPrice': 12.345}])
        self.assertEqual(body['taxes'], [{'rate': 22, 'amount': 5.43}])
        credit = parse_invoice(XML.replace('TD01', 'TD04').replace('12.345', '-12.345').replace('5.43', '-5.43'), 'conn_Example')
        self.assertEqual(credit['documentType'], 'credit_note')
        self.assertEqual(credit['lines'][0]['unitPrice'], -12.345)
        self.assertEqual(credit['taxes'][0]['amount'], -5.43)

    def test_unsupported_and_bounded_xml(self):
        for xml in [XML.replace('TD01', 'TD02'), XML.replace('2.00', '-2.00'), XML.replace('12.345', 'NaN'),
                    '<!DOCTYPE x [<!ENTITY bad SYSTEM "file:///etc/passwd">]>' + XML,
                    XML.replace('</p:FatturaElettronica>', XML.split('<FatturaElettronicaBody>')[1].split('</p:')[0] + '</p:FatturaElettronica>'),
                    XML + ' ' * 1048576, '<broken>']:
            with self.subTest(xml=xml[:35]), self.assertRaises(ValueError):
                parse_invoice(xml, 'conn_Example')
        with self.assertRaises(ValueError):
            parse_invoice(XML, 'wrong-account')

    def test_original_account_headers_and_one_submit(self):
        calls = []
        def transport(method, url, headers, body):
            calls.append((url, headers, body))
            return 200, {'can_run': True} if url.endswith('/estimate') else {'ref': 'fixture-ref', 'status': 'pending'}
        client = PramaanClient(api_key='fixture', transport=transport)
        body = parse_invoice(XML, 'conn_Example')
        client.estimate('edi.einvoice.submit', body, account='conn_Example')
        client.call('edi.einvoice.submit', body, account='conn_Example', idempotency_key='one', approved_by='fixture-user')
        client.run('edi.einvoice.status.get', {'ref': 'fixture-ref'}, account='conn_Example')
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(call[1]['Pramaan-Account'] == 'conn_Example' for call in calls))
        self.assertEqual(calls[1][1]['Idempotency-Key'], 'one')

    def test_only_explicit_no_effect_proof_releases_server_failure(self):
        body = parse_invoice(XML, 'conn_Example')
        for effect, uncertain in [('none', False), (None, True), ('unknown', True)]:
            with self.subTest(effect=effect):
                client = PramaanClient(api_key='fixture', transport=lambda *args: (503, {'error': {'code': 'upstream_unavailable', 'effect': effect}}))
                with self.assertRaises(PramaanError) as raised:
                    client.run('edi.einvoice.submit', body, account='conn_Example', idempotency_key='one')
                self.assertEqual(raised.exception.uncertain, uncertain)

    def test_http_retains_only_bounded_no_effect_fact(self):
        import io
        import json
        from urllib.error import HTTPError
        from unittest.mock import Mock
        error = HTTPError('https://api.pramaan.dev/test', 503, 'Unavailable', {}, io.BytesIO(json.dumps({'error': {'code': 'upstream_unavailable', 'effect': 'none', 'message': 'must-not-leak', 'provider': 'must-not-leak'}}).encode()))
        client = PramaanClient(api_key='fixture')
        client._transport = client._http
        with patch('erpnext.pramaan.build_opener', return_value=Mock(open=Mock(side_effect=error))):
            with self.assertRaises(PramaanError) as raised:
                client.run('edi.einvoice.submit', parse_invoice(XML, 'conn_Example'), account='conn_Example', idempotency_key='one')
        self.assertFalse(raised.exception.uncertain)
        self.assertNotIn('must-not-leak', str(raised.exception))

    def test_line_tax_and_multi_body_limits(self):
        import copy
        from xml.etree import ElementTree as ET
        for kind, count in [('DettaglioLinee', 1000), ('DatiRiepilogo', 100)]:
            root = ET.fromstring(XML)
            goods = root.find('FatturaElettronicaBody/DatiBeniServizi')
            for _ in range(count): goods.append(copy.deepcopy(goods.find(kind)))
            with self.assertRaises(ValueError): parse_invoice(ET.tostring(root, encoding='unicode'), 'conn_Example')
        root = ET.fromstring(XML);root.append(copy.deepcopy(root.find('FatturaElettronicaBody')))
        with self.assertRaises(ValueError): parse_invoice(ET.tostring(root, encoding='unicode'), 'conn_Example')

    def test_fake_shapes_and_uncertainty_are_never_retried(self):
        body = parse_invoice(XML, 'conn_Example')
        for mode in ['pending', 'accepted', 'rejected', 'delivery_unavailable', 'refused', 'unavailable', 'connection_required', 'uncertain']:
            with self.subTest(mode=mode), patch.dict(os.environ, {'PRAMAAN_FAKE': '1', 'PRAMAAN_API_KEY': '', 'PRAMAAN_FAKE_EINVOICE': mode}), patch.object(PramaanClient, '_http', side_effect=AssertionError('Live calls forbidden')):
                client = PramaanClient()
                if mode in ['refused', 'unavailable', 'connection_required', 'uncertain']:
                    with self.assertRaises(PramaanError) as raised:
                        client.run('edi.einvoice.submit', body, account='conn_Example', idempotency_key='one')
                    self.assertEqual(raised.exception.uncertain, mode == 'uncertain')
                    with self.assertRaises(PramaanError):
                        client.run('edi.einvoice.status.get', {'ref': 'fixture'}, account='conn_Example')
                else:
                    self.assertEqual(client.run('edi.einvoice.submit', body, account='conn_Example', idempotency_key='one')['status'], 'pending')
                    result = client.run('edi.einvoice.status.get', {'ref': 'fixture'}, account='conn_Example')
                    self.assertEqual(result['status'], 'accepted' if mode == 'delivery_unavailable' else mode)
        calls = []
        def uncertain(*args):
            calls.append(args)
            return 502, {'error': {'code': 'upstream_unavailable'}}
        client = PramaanClient(api_key='fixture', transport=uncertain)
        with self.assertRaises(PramaanError) as raised:
            client.call('edi.einvoice.submit', body, account='conn_Example', idempotency_key='one')
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(len(calls), 1)
