"""Run in a disposable PRAMAAN_FAKE=1 stack; no external calls are permitted."""
import os
from unittest.mock import patch
if os.environ.get('PRAMAAN_FAKE') != '1':
    raise SystemExit('Use a disposable fake-only stack.')
os.chdir('/app/.runtime/bench/sites')
import frappe
from erpnext.pramaan import PramaanClient
from erpnext.erp_integrations.pramaan import payment_account as account
from frappe.app import application
from werkzeug.test import Client
from werkzeug.wrappers import Response

site=os.environ['ERP_SITE_NAME']
frappe.init(site=site); frappe.connect(); frappe.set_user('Administrator')
if not frappe.db.exists('User','account-viewer@erp.test'):
    frappe.get_doc({'doctype':'User','email':'account-viewer@erp.test','first_name':'Account Viewer',
                   'send_welcome_email':0,'new_password':'fixture-local-only','roles':[{'role':'Sales User'}]}).insert(ignore_permissions=True)
frappe.db.commit(); frappe.destroy()

calls=[]; state='incomplete'
def transport(method,url,headers,body):
    calls.append((url,headers,body))
    if url.endswith('/estimate'): return 200, {'can_run':True}
    if url.endswith('.connect'): return 200, {'onboardingMode':'embedded'}
    if url.endswith('.session.create'): return 200, {'clientSecret':'fixture_secret_only','publishableKey':'pk_test_fixture','private':'must_not_leak'}
    if state=='not_connected': return 409, {'error':{'code':'connection_required'}}
    return 200, {'status':'ready' if state=='ready' else 'pending','chargesEnabled':state=='ready',
        'payoutsEnabled':state=='ready','requirementsDue':['external_account','company.tax_id']}
client=PramaanClient(api_key='fixture-only',transport=transport)
web=Client(application,Response); base='http://'+site
prefix='/api/method/'+account.__name__+'.'
def invoke(method,**data):
    r=web.post(prefix+method,base_url=base,data=data)
    assert r.status_code==200,(method,r.status_code,r.get_data(as_text=True))
    return r
with patch.object(account,'get_client',return_value=client), patch.object(PramaanClient,'_http',side_effect=AssertionError('Live calls forbidden')):
    r=web.post(prefix+'session',base_url=base)
    assert r.status_code in {401,403} and r.headers.get('Cache-Control')=='no-store'
    assert not calls
    assert web.post('/api/method/login',base_url=base,data={'usr':'Administrator','pwd':os.environ['ERP_ADMIN_PASSWORD']}).status_code==200
    for state in ['not_connected','incomplete','ready']:
        assert invoke('status').get_json()['message']['state']==state
    estimate=invoke('connect',country='GB').get_json()['message']
    assert not any(url.endswith('.connect') for url,_,_ in calls)
    assert invoke('connect',confirmation=estimate['confirmation'],country='GB').get_json()['message']=={'mode':'embedded'}
    first=invoke('session',account='untrusted-input')
    assert set(first.get_json()['message'])=={'clientSecret','publishableKey'}
    assert first.headers.get('Cache-Control')=='no-store'
    invoke('session')
    keys=[headers['Idempotency-Key'] for url,headers,_ in calls if url.endswith('.session.create')]
    assert len(set(keys))==2
    assert calls[-1][2]=={'components':account.COMPONENTS}
    web.post('/api/method/logout',base_url=base)
    web.post('/api/method/login',base_url=base,data={'usr':'account-viewer@erp.test','pwd':'fixture-local-only'})
    count=len(calls)
    for method in ['status','connect','session']:
        assert web.post(prefix+method,base_url=base).status_code==403
    assert count==len(calls)
print('PASS: real HTTP authorization, all account states, connect approval, filtered session reply, no-store and fresh session keys; fake transport only.')
