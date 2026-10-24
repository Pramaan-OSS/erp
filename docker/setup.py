"""Prepare only the local site in this compose project's private volumes."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(os.environ.get("ERP_APP_ROOT", "/app")).resolve()
BENCH = ROOT / ".runtime/bench"
SITES = BENCH / "sites"
DB_TYPE = os.environ.get("ERP_DB", "mariadb")
if DB_TYPE not in {"mariadb", "postgres"}:
    raise SystemExit("ERP_DB must be mariadb or postgres.")
DB_PORT = "5432" if DB_TYPE == "postgres" else "3306"
DB_HOST = os.environ.get("ERP_DB_HOST", "database")
REDIS_HOST = os.environ.get("ERP_REDIS_HOST", "cache")
SITE = os.environ.get("ERP_SITE_NAME", "erp.localhost")
if not SITE or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in SITE):
    raise SystemExit("The local site name must contain only lowercase letters, numbers, dots and hyphens.")
for folder in [SITES, BENCH / "apps", BENCH / "logs"]:
    folder.mkdir(parents=True, exist_ok=True)
for target, source in [(BENCH / "env", ROOT / ".venv"), (BENCH / "apps/frappe", ROOT / "vendor/framework"), (BENCH / "apps/erpnext", ROOT)]:
    if not target.exists():
        target.symlink_to(source, target_is_directory=True)
(SITES / "apps.txt").write_text("frappe\nerpnext\n")
(SITES / "common_site_config.json").write_text(json.dumps({
    "db_host": DB_HOST, "db_port": int(DB_PORT), "use_mysqlclient": 0,
    "redis_cache": f"redis://{REDIS_HOST}:6379/0", "redis_queue": f"redis://{REDIS_HOST}:6379/1", "redis_socketio": f"redis://{REDIS_HOST}:6379/2",
    "socketio_port": 9000, "socketio_same_origin": True, "webserver_port": 8000, "webserver_host": "0.0.0.0",
    "default_site": SITE, "serve_default_site": True, "developer_mode": 0, "allow_error_traceback": 0,
    "server_script_enabled": 0, "enable_telemetry": False, "pause_scheduler": False, "disable_scheduler": False,
    "encryption_key": os.environ["ERP_ENCRYPTION_KEY"],
    "chromium_path": "/usr/bin/chromium",
}, indent=2))
(SITES / "common_site_config.json").chmod(0o600)

def bench(*args):
    result = subprocess.run([str(ROOT / ".venv/bin/python"), "-m", "frappe.utils.bench_helper", "frappe", *args], cwd=SITES)
    if result.returncode:
        raise SystemExit("Local site setup did not finish. Check the private container logs.")

config_path = SITES / SITE / "site_config.json"
if not config_path.exists():
    bench("new-site", SITE, "--db-type", DB_TYPE, "--db-host", DB_HOST, "--db-port", DB_PORT,
          "--db-root-username", "postgres" if DB_TYPE == "postgres" else "root",
          "--db-root-password", os.environ["LOCAL_DB_PASSWORD"], "--admin-password", os.environ["ERP_ADMIN_PASSWORD"],
          *(["--mariadb-user-host-login-scope", "%"] if DB_TYPE == "mariadb" else []),
          "--set-default", "--install-app", "erpnext")
config = json.loads(config_path.read_text())
if config.get("db_type", "mariadb") != DB_TYPE:
    raise SystemExit("ERP_DB differs from the existing site. Use a separate compose project for each database.")
config.update(developer_mode=0, allow_error_traceback=0, host_name=f"http://localhost:{os.environ.get('ERP_LOCAL_PORT', '18010')}")
config_path.write_text(json.dumps(config, indent=2)); config_path.chmod(0o600)
assets = SITES / "assets"; assets.mkdir(exist_ok=True)
for name, source in [("erpnext", ROOT / "erpnext/public"), ("frappe", ROOT / "vendor/framework/frappe/public")]:
    link = assets / name
    if not link.exists():
        link.symlink_to(source, target_is_directory=True)
assets_json = assets / "assets.json"
bench("--site", SITE, "migrate")
# Bundling takes minutes, so skip it when every listed bundle exists. The list lives in the
# sites volume but the bundles live in the container, so a recreated container must rebuild.
needs_build = True
if assets_json.exists():
    try:
        built = json.loads(assets_json.read_text())
        needs_build = not any("erpnext" in key for key in built) or not all(
            (SITES / str(path).lstrip("/")).exists() for path in built.values())
    except ValueError:
        needs_build = True
if needs_build:
    bench("build")
    if not assets_json.exists():
        (assets_json).write_text("{}")
bench("--site", SITE, "enable-scheduler")
from erpnext.pramaan import PramaanClient
(BENCH / ".outside-configured").write_text("yes" if PramaanClient().configured else "no")
