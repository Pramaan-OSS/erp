"""The expected empty-filter state must not reach the report request client."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('report_patch', Path(__file__).resolve().parents[1] / 'scripts/patch-framework.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReportValidationTests(unittest.TestCase):
    def test_missing_filters_stop_before_request_and_other_errors_propagate(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'frappe/public/js/frappe/views/reports/query_report.js'
            path.parent.mkdir(parents=True)
            path.write_text('function refresh() {\n' + module.BEFORE + '\n this.fakeClient.call(filters); return Promise.resolve(); }')
            module.patch(root)
            patched = path.read_text()
            module.patch(root)
            self.assertEqual(path.read_text(), patched)
            script = patched + '''
                (async () => {
                    const calls = [];
                    const view = {fakeClient: {call: filters => calls.push(filters)},
                                  get_filter_values: () => {throw "Filter missing";}};
                    await refresh.call(view);
                    if (calls.length) throw Error("Missing filters reached the client");
                    view.get_filter_values = () => ({company: "Walk Company"});
                    await refresh.call(view);
                    if (calls.length !== 1 || calls[0].company !== "Walk Company") throw Error("Valid report did not run");
                    view.get_filter_values = () => {throw Error("Unexpected failure");};
                    try {await refresh.call(view);} catch (error) {
                        if (error.message === "Unexpected failure") return;
                        throw error;
                    }
                    throw Error("Unexpected errors must propagate");
                })().catch(error => {console.error(error); process.exit(1);});
            '''
            result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_documentation_metadata_keeps_links_local(self):
        import json
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "frappe/core/doctype/sample/sample.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"documentation": "https://outside.test/docs", "fields": [
                {"documentation_url": "https://outside.test/field"}, {"label": "Keep this"}]}))
            module.local_help(root)
            data = json.loads(path.read_text())
            self.assertEqual(data["documentation"], "/help")
            self.assertEqual(data["fields"][0]["documentation_url"], "/help")
            self.assertEqual(data["fields"][1]["label"], "Keep this")

    def test_map_tiles_use_only_the_bundled_local_asset(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "frappe/public/js/frappe/utils/utils.js"
            path.parent.mkdir(parents=True)
            path.write_text('const config={\n\tmap_defaults: {tiles:{url:"https://outside.test/tile"}},\n\tdesktop_icon(){} };')
            module.local_maps(root)
            source = path.read_text()
            self.assertNotIn("https://", source)
            script = source + '''
                const fakeClient = {get: url => {if(!url.startsWith("/assets/erpnext/")) throw Error("Outside request");}};
                for(const tile of Object.values(config.map_defaults.tiles)) {
                    fakeClient.get(tile.url);
                    if(tile.options.attribution) throw Error("Outside attribution");
                }
            '''
            result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_blocked_decorative_sound_does_not_raise_an_unhandled_error(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"frappe/public/js/frappe/utils/utils.js"
            path.parent.mkdir(parents=True)
            path.write_text('function playSound(audio) { audio.play(); }')
            module.local_sounds(root)
            script=path.read_text()+'''
                let rejected=false;
                process.on("unhandledRejection",()=>{rejected=true;});
                playSound({play:()=>Promise.reject(Error("Playback blocked"))});
                setImmediate(()=>{if(rejected)process.exit(1);});
            '''
            result=subprocess.run(["node","-e",script],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
