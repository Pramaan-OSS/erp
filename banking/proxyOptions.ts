import { readFileSync } from 'node:fs';

// Dev-only proxy settings. When no bench is present (a plain image build),
// the local defaults keep the dev server usable.
let webserver_port: string | number = 8000;
try {
	const common_site_config = JSON.parse(
		readFileSync(new URL('../../../sites/common_site_config.json', import.meta.url), 'utf8')
	) as { webserver_port: string | number };
	webserver_port = common_site_config.webserver_port;
} catch {
	// no bench: use the default local port
}

export default {
	'^/(app|api|assets|files|private)': {
		target: `http://127.0.0.1:${webserver_port}`,
		ws: true,
		router: function (req) {
			const site_name = req.headers?.host?.split(':')[0];
			return `http://${site_name ?? 'localhost'}:${webserver_port}`;
		}
	}
};
