"""The bank connection form uses a fake hosted-link client."""
import subprocess
import unittest
from pathlib import Path


class BankConnectionFormTests(unittest.TestCase):
    def test_hosted_picker_and_return_state(self):
        source=(Path(__file__).resolve().parents[1]/'erpnext/erp_integrations/doctype/banking_connection_settings/banking_connection_settings.js').read_text()
        script='''let handlers,prompt,request;const values={};
        const sessionStorage={getItem:k=>values[k],setItem:(k,v)=>values[k]=v,removeItem:k=>delete values[k]};
        const window={location:{href:"",search:"",pathname:"/app/banking-connection-settings"},history:{replaceState:()=>{}}};
        const __=s=>s;
        const frappe={ui:{form:{on:(name,h)=>handlers=h}},defaults:{get_user_default:()=>"Walk Company"},
            prompt:(fields,callback)=>prompt={fields,callback},
            xcall:(method,args)=>{request={method,args};return Promise.resolve({ref:"owned-bank",connectUrl:"https://pramaan.test/connect/opaque"});},
            msgprint:()=>{throw Error("Unexpected failure");}};
        '''+source+'''
        (async()=>{
            connect_bank({doc:{default_country:"GB"}});
            if(prompt.fields.some(f=>f.fieldname==="institution"||f.fieldname==="query")) throw Error("Must use the hosted bank picker");
            prompt.callback({country:"GB",company:"Walk Company"});
            await Promise.resolve();await Promise.resolve();
            if(JSON.stringify(request.args)!==JSON.stringify({country:"GB"})) throw Error("Unexpected institution input");
            if(window.location.href!=="https://pramaan.test/connect/opaque") throw Error("Hosted link was modified");
            window.location.search="?bank_return=1";
            handlers.refresh({doc:{}});
            if(prompt.fields[0].fieldname!=="bank_name"||prompt.fields[1].default!=="Walk Company") throw Error("Return state not restored");
        })().catch(e=>{console.error(e);process.exit(1);});'''
        result=subprocess.run(['node','-e',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
