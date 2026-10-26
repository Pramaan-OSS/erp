"""Exercise the actual HTTP input validation and permission boundary offline."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

if os.environ.get('PRAMAAN_FAKE') != '1' or os.environ.get('PRAMAAN_API_KEY'):
    raise SystemExit('Use fake transport and an empty key.')
root = Path(os.environ.get('ERP_APP_ROOT', '/app'))
sys.path.insert(0, str(root / 'review'))
os.chdir(root / '.runtime/bench/sites')
import frappe
from italy_fixture import seed
from frappe.app import application
from werkzeug.test import Client
from werkzeug.wrappers import Response
from erpnext.pramaan import PramaanClient

frappe.init(site=os.environ['ERP_SITE_NAME']); frappe.connect(); frappe.set_user('Administrator')
name, company = seed()
frappe.destroy()
env_file = dict(line.split('=', 1) for line in (root / '.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
admin_password = os.environ.get('ERP_ADMIN_PASSWORD') or env_file['ERP_ADMIN_PASSWORD']
web = Client(application, Response)
base = 'http://' + os.environ['ERP_SITE_NAME']
prefix = '/api/method/erpnext.erp_integrations.pramaan.italy_einvoice.'
def post(method, **values):
    response = web.post(prefix + method, base_url=base, data=values)
    assert response.status_code == 200, (method, response.status_code, response.get_data(as_text=True))
    return response.get_json()['message']
with patch.object(PramaanClient, '_http', side_effect=AssertionError('Live calls forbidden')):
    for method, data in [('action', {'docname': name}), ('configure', {'company': company, 'connection': 'conn_Example'})]:
        assert web.post(prefix + method, base_url=base, data=data).status_code in {401, 403}
    assert web.post('/api/method/login', base_url=base, data={'usr': 'Administrator', 'pwd': admin_password}).status_code == 200
    assert post('configure', company=company, connection='conn_Example')['configured']
    preview = post('action', docname=name, operation='prepare')
    assert preview['state'] == 'Confirm'
    assert preview['xmlUrl'].startswith('/private/files/')
    assert 'xml' not in json.dumps(preview['document']) and 'connectionRef' not in preview['document']
    assert post('action', docname=name, operation='confirm', confirmation=preview['confirmation'])['state'] == 'Pending'
    with patch.dict(os.environ, {'PRAMAAN_FAKE_EINVOICE': 'accepted'}):
        assert post('action', docname=name, operation='refresh')['receipt'] == 'delivered'
    assert 'result_ref' not in post('action', docname=name)
print('PASS: HTTP input types, guest denial, administrator setup, private XML preview, confirmed pending and accepted receipt; no live transport.')
