"""Handle the pinned report engine's expected missing-filter state."""
from pathlib import Path
import json

BEFORE = '\t\tlet filters = this.get_filter_values(!this.prepared_report_name);'
AFTER = '''\t\tlet filters;
		try {
			filters = this.get_filter_values(!this.prepared_report_name);
		} catch (error) {
			// The filter control already shows the validation message.
			if (error !== "Filter missing") throw error;
			return Promise.resolve();
		}'''


def patch(root):
    target = Path(root) / 'frappe/public/js/frappe/views/reports/query_report.js'
    source = target.read_text()
    if AFTER not in source and source.count(BEFORE) != 1:
        raise RuntimeError('The report engine changed; review the missing-filter fix before building.')
    target.write_text(source.replace(BEFORE, AFTER))
    local_help(root)
    local_maps(root)
    local_sounds(root)


def local_help(root):
    root = Path(root)
    def rewrite(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"documentation", "documentation_url"} and isinstance(item, str) and item.startswith(("https://", "http://")):
                    value[key] = "/help"
                else:
                    rewrite(item)
        elif isinstance(value, list):
            for item in value:
                rewrite(item)
    for target in (root / "frappe").rglob("*.json"):
        original = target.read_text()
        try:
            value = json.loads(original)
        except ValueError:
            continue
        before = json.dumps(value)
        rewrite(value)
        if before != json.dumps(value):
            target.write_text(json.dumps(value, indent=1) + "\n")
    target = root / "frappe/core/page/permission_manager/permission_manager_help.html"
    if target.exists():
        text = target.read_text().replace(
            'If these instructions where not helpful, please add in your suggestions on GitHub Issues.',
            'For more help, search the local documentation.')
        text = text.replace('https://github.com/frappe/frappe/issues', '/help').replace('Submit an Issue', 'Local help')
        target.write_text(text)
    target = root / "frappe/public/js/frappe/form/form.js"
    if target.exists():
        text = target.read_text()
        start = text.index("\n\tshow_report_bug_link() {")
        end = text.index("\n\tadd_web_link(", start)
        text = text[:start] + '\n\tshow_report_bug_link() {\n\t\tif (this.meta.beta) this.add_web_link("/help", __("Help"));\n\t}\n' + text[end:]
        target.write_text(text)


def local_maps(root):
    root = Path(root)
    target = root / "frappe/public/js/frappe/utils/utils.js"
    if target.exists():
        text = target.read_text()
        start = text.index("\n\tmap_defaults: {")
        end = text.index("\n\tdesktop_icon(", start)
        tile = '{ url: "/assets/erpnext/images/map-background.svg", options: {} }'
        block = '\n\tmap_defaults: {\n\t\tcenter: [19.08, 72.8961], zoom: 13,\n\t\ttiles: {\n'
        for key in ("default_tile", "satellite_tile", "labels_tail", "terrain_lines_tail"):
            block += "\t\t\t" + key + ": " + tile + ",\n"
        block += '\t\t},\n\t\timage_path: "/assets/frappe/images/leaflet/",\n\t},\n'
        target.write_text(text[:start] + block + text[end:])
    target = root / "frappe/public/js/frappe/form/controls/geolocation.js"
    if target.exists():
        text = target.read_text()
        start = text.index("\n\tbind_leaflet_layers_control() {")
        end = text.index("\n\tbind_leaflet_locate_control() {", start)
        target.write_text(text[:start] + "\n\tbind_leaflet_layers_control() {}\n" + text[end:])
    target = root / "frappe/public/js/leaflet.bundle.js"
    if target.exists():
        text = target.read_text()
        setting = "L.Map.mergeOptions({ attributionControl: false });"
        if setting not in text:
            target.write_text(text + "\n" + setting + "\n")


def local_sounds(root):
    target = Path(root) / "frappe/public/js/frappe/utils/utils.js"
    if not target.exists():
        return
    text = target.read_text()
    before = "audio.play();"
    after = "const playback = audio.play();\n\t\t\tif (playback?.catch) playback.catch(() => {});"
    if after in text:
        return
    if before not in text:
        return
    target.write_text(text.replace(before, after, 1))


if __name__ == '__main__':
    import sys
    patch(sys.argv[1] if len(sys.argv) > 1 else 'vendor/framework')
