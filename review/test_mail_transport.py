"""Mail contract checks with fake persistence and a fake service client."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from test_integration_contracts import install_frappe_stub
import frappe
from erpnext.erp_integrations.pramaan import pramaan_mail as mail


class Outbox(SimpleNamespace):
    def reload(self):
        pass

    def db_set(self, field, value=None):
        self.__dict__.update(field if isinstance(field, dict) else {field: value})


class MailTests(unittest.TestCase):
    def test_one_sender_without_an_email_account(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mail.sender_account('old@local.invalid'), 'ERP <noreply@updates.pramaan.one>')
        with patch.dict(os.environ, {'PRAMAAN_EMAIL_FROM': 'ERP <custom@owner.test>'}):
            self.assertEqual(mail.sender_account(), 'ERP <custom@owner.test>')

    def test_queue_uses_platform_send_and_no_unconfigured_reply_to(self):
        saved = []
        class Doc(dict):
            name = 'queue-1'
            def insert(self, **kw):
                saved.append(self)
                return self
        with patch.multiple(frappe, get_doc=lambda d: Doc(d), session=SimpleNamespace(user='Administrator'),
                            enqueue=lambda *a, **kw: None, _dict=lambda **kw: SimpleNamespace(**kw), create=True):
            mail.sendmail(recipients=['recipient@owner.test'], subject='Receipt', message='<p>Accepted</p>')
        self.assertEqual(saved[0]['capability'], 'email.send')
        self.assertTrue(saved[0]['idempotency_key'])
        payload = json.loads(saved[0]['payload'])
        self.assertNotIn('replyTo', payload)
        self.assertEqual(payload['from'], mail.sender_account())

    def test_no_legacy_queue_field_does_not_crash_delivery(self):
        from unittest.mock import Mock
        get_all = Mock(side_effect=AssertionError("A missing column must never be queried"))
        with patch.multiple(frappe, db=SimpleNamespace(has_column=lambda *a: False), get_all=get_all, create=True):
            mail.finish_legacy_queue(Outbox(name="out-1"), "Sent")
        get_all.assert_not_called()

    def test_platform_ref_is_acceptance_but_not_delivery_tracking(self):
        for trackable in (False, True, None):
            row = Outbox(state='Pending', capability='email.send', payload='{}', idempotency_key='stable-1',
                         requested_by='Administrator', communication='comm-1', name='out-1')
            changes = []
            calls = []
            class FakeClient:
                def call(self, capability, payload, **kw):
                    calls.append((capability, kw))
                    return dict(ref='owned-reference', **({'trackable': trackable} if trackable is not None else {}))
            db = SimpleNamespace(sql=lambda *a: None, commit=lambda: None, has_column=lambda *a: False,
                                 set_value=lambda *a: changes.append(a))
            with patch.multiple(frappe, db=db, get_doc=lambda *a: row, get_all=lambda *a, **kw: [], create=True), patch.object(mail, 'client', FakeClient):
                mail.deliver(row.name)
            self.assertEqual(row.state, 'Accepted')
            self.assertEqual(row.trackable, trackable is True)
            self.assertEqual(changes[0][2]['delivery_status'], 'Sent' if trackable is True else '')
            self.assertEqual(calls[0], ('email.send', {'idempotency_key': 'stable-1'}))

class AttachmentTests(unittest.TestCase):
    def test_attachments_upload_to_file_handles_before_send(self):
        import base64
        row = Outbox(state='Pending', capability='email.send', payload=json.dumps({
            'attachments': [{'filename': 'invoice.pdf', 'content': base64.b64encode(b'%PDF-test').decode(),
                             'mimeType': 'application/pdf'}]}), idempotency_key='stable-upload',
                     requested_by='Administrator', communication=None, name='out-upload')
        calls = []
        class FakeClient:
            def upload_file(self, content, content_type, **kwargs):
                calls.append(('upload', content, content_type, kwargs))
                return {'fileId': 'file_owned'}
            def call(self, capability, body, **kwargs):
                calls.append(('send', capability, body, kwargs))
                return {'ref': 'owned-reference', 'trackable': False}
        db = SimpleNamespace(sql=lambda *a: None, commit=lambda: None, has_column=lambda *a: False)
        with patch.multiple(frappe, db=db, get_doc=lambda *a: row, create=True), patch.object(mail, 'client', FakeClient):
            mail.deliver(row.name)
        self.assertEqual(calls[0], ('upload', b'%PDF-test', 'application/pdf', {'idempotency_key': 'stable-upload-0'}))
        self.assertEqual(calls[1][2]['attachments'], [{'fileId': 'file_owned', 'name': 'invoice.pdf'}])
        self.assertEqual(row.state, 'Accepted')
        self.assertNotIn('content', json.loads(row.payload)['attachments'][0])
