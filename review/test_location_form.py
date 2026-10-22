"""Location form checks use a fake map and never load remote tiles."""
import json
import subprocess
import unittest
from pathlib import Path


class LocationTests(unittest.TestCase):
    def test_map_absent_and_ready(self):
        source = (Path(__file__).resolve().parents[1] / 'erpnext/assets/doctype/location/location.js').read_text()
        script = '''let handlers;const frappe={ui:{form:{on:(name,h)=>handlers=h}}};\n''' + source + '''
        let doc={latitude:3,longitude:4};
        handlers.onload_post_render({doc,fields_dict:{location:{}}});
        if(doc.latitude!==3||doc.longitude!==4) throw Error("Existing coordinates changed without a map");
        let centered;
        handlers.onload_post_render({doc,fields_dict:{location:{map:{setView:(coords,zoom)=>centered=[coords,zoom]}}}});
        if(JSON.stringify(centered)!==JSON.stringify([[3,4],13])) throw Error("Saved coordinates not restored");
        doc={};
        handlers.onload_post_render({doc,fields_dict:{location:{map:{getCenter:()=>({lat:1,lng:2})}}}});
        if(doc.latitude!==1||doc.longitude!==2) throw Error("Map coordinates not copied");
        '''
        result=subprocess.run(['node','-e',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
