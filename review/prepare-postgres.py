"""Create a disposable Postgres site for CI, using generated local credentials."""
import json
import os
from pathlib import Path
import runpy

root = Path.cwd()
if os.environ.get("PRAMAAN_FAKE") != "1" or os.environ.get("PRAMAAN_API_KEY"):
    raise SystemExit("Use fake mode and an empty key.")
os.environ.update(ERP_APP_ROOT=str(root), ERP_DB="postgres",
                  ERP_DB_HOST=os.environ.get("ERP_DB_HOST", "127.0.0.1"),
                  ERP_REDIS_HOST=os.environ.get("ERP_REDIS_HOST", "127.0.0.1"),
                  ERP_SITE_NAME="postgres.test")
runpy.run_path(str(root / "scripts/local-config.py"))["configure"](root)
for line in (root / ".env").read_text().splitlines():
    name, _, value = line.partition("=")
    if name in {"LOCAL_DB_PASSWORD", "ERP_ADMIN_PASSWORD", "ERP_ENCRYPTION_KEY"}:
        # CI service password is supplied by the job, never an external credential.
        os.environ.setdefault(name, value)
os.environ.update(FRAPPE_PRELOAD_DATABASE_DRIVERS="none", FRAPPE_BENCH_ROOT=str(root / ".runtime/bench"))
runpy.run_path(str(root / "docker/setup.py"))
config_path = root / ".runtime/bench/sites/postgres.test/site_config.json"
config = json.loads(config_path.read_text())
config["allow_tests"] = True
config_path.write_text(json.dumps(config, indent=2))
runpy.run_path(str(root / "review/check_database.py"), run_name="__main__")
