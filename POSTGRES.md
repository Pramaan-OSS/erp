# Postgres trial — 2026-10-24

Verdict: **works with caveats** on Postgres 16. A fresh site installs, migrates,
and runs the tested accounting, stock, selling, buying and setup workflows.
MariaDB remains the default. This adds an option for a new site; it does not
convert existing MariaDB data.

## Changes

- `ERP_DB=postgres` selects `postgres:16`; the default selects MariaDB 11.8.
  Compose includes the matching database definition. Each uses its own database
  volume; `./start` selects project `erp-pg` and image `erp-pg-app` for Postgres.
- Site creation selects the correct database type, port and root user. A site
  refuses to start with a different database type from its existing configuration.
- The image includes the Postgres **16** client tools, including working backups.
- Setup accepts local host/root overrides for the CI smoke job. Normal Docker
  paths and hosts retain their defaults.
- Real database smoke checks cover customer persistence and permission-checked
  lookups, schema backups, sign-in settings, site configuration, email delivery
  state, and bank-transfer row locks and JSON persistence.
- The payments-account HTTP check now uses the package's fake session client and
  rejects HTTP transport calls. No upstream application modules were patched.
- The client module supports fake payment-link creation, estimates and empty
  paid-order lists with an empty key. Stable local links require an idempotency
  key; the fake never declares that money arrived. Production calls, custom
  transports and other unconfigured features retain their key requirements.
  Three regression checks cover fake behavior and the real-call boundary.

The local image was built once. Missing client tools, then the matching client
major version, were installed as small updates to that image rather than
rebuilding the dependency image. Final source files were copied into the image.

## Test results

The same five upstream modules ran on fresh sites on each database, with
`run-tests --lightmode --module …` after warming `erpnext.tests.bootstrap_test_data`.

| Module | Postgres pass / fail | MariaDB pass / fail |
| --- | ---: | ---: |
| `erpnext.accounts.doctype.account.test_account` | 10 / 0 | 10 / 0 |
| `erpnext.stock.doctype.stock_entry.test_stock_entry` | 169 / 0 | 169 / 0 |
| `erpnext.selling.doctype.sales_order.test_sales_order` | 128 / 0 | 128 / 0 |
| `erpnext.buying.doctype.purchase_order.test_purchase_order` | 88 / 0 | 88 / 0 |
| `erpnext.setup.doctype.company.test_company` | 12 / 0 | 12 / 0 |
| **Upstream subset total** | **407 / 0** | **407 / 0** |
| `python -m unittest discover -s review` | 96 / 0 | 96 / 0 |
| `python review/check_database.py` | 7 / 0 | 7 / 0 |
| `node --test "erpnext/tests/js/**/*.test.mjs"` | 10 / 0 | 10 / 0 |

The real HTTP payments-account check also passes on both databases: authorization,
three account states, approval before connecting, filtered session replies,
no-store headers, fresh session keys, and denial for a non-administrator.
No tests were skipped in these runs. Before repeating the sales-order module,
its two previously committed workflow fixtures (`SO Test Workflow` and
`SO Edit Perm Workflow`) were deactivated on both disposable sites and caches
cleared. Otherwise an unrelated amendment test inherits an active workflow from
the earlier run. The module reactivates its workflows for the tests that need them.

Postgres-specific upstream failures: **none observed in this subset**.
The initial shared failure below was resolved by the follow-up fake-client fix.
The complete sales-order module was rerun on both databases: 128 passed on each,
including `test_sales_order_advance_payment_status`. There are now no failures
in the selected subset.

Initial failure and resolution:

| Test | Error | Cause |
| --- | --- | --- |
| `erpnext.selling.doctype.sales_order.test_sales_order.TestSalesOrder.test_sales_order_advance_payment_status` | `ValidationError: Add PRAMAAN_API_KEY to .env` | The client originally required a key before reaching its built-in fake transport. Fake mode now creates a deterministic local payment link with an empty key; the unchanged test passes on both databases. |

The full upstream suite was not run. There are 6,211 test methods across 560 test
files; the 407-test subset took about 12 minutes on Postgres including warmup.
A simple runtime projection exceeds 90 minutes on this shared machine, so the
trial uses the brief's representative-subset option. This is an estimate, not a
measurement of the full suite. The company module alone took 447 seconds on
Postgres versus 269 seconds on MariaDB; these are shared-machine timings, not a
production performance comparison. The framework still labels Postgres support
experimental at site creation.

## Browser evidence

A headless Playwright walk on the Postgres site signed in as Administrator,
created a customer and service item, created and submitted a sales invoice,
recorded a submitted payment, and reopened the invoice with status **Paid** and
zero outstanding balance. The fixture company adds tax and rounds the amount
payable to 12; the recorded payment matches that amount.

The bank-transfer dialog opens and reads its persisted request state. The
payments-account page opens and shows its expected unconfigured-account error
with an empty key. Account readiness and sessions were separately exercised by
the fake HTTP check; no real account onboarding or settlement was attempted.
The browser recorded zero uncaught errors and zero outside requests.

A second walk set `PRAMAAN_FAKE_ACCOUNT_STATE` to `not_connected`, `incomplete` and
`ready` in turn. The page showed each state correctly, with requirement labels and
enabled flags, and the connect approval step. In fake mode the embedded account
components cannot open, because they need a real session, so the page shows
"Could not open your payments account" under the status. This walk also found that a
recreated app container served a blank desk: built bundles live in the container but
the bundle list lives in the sites volume. Setup now rebuilds when a listed bundle is
missing. This affected MariaDB too.

Screenshots, the walk script, stage results, individual test logs and CI proof
are in `.scratch/postgres/` (untracked). Main screenshots are `invoice-paid.png`,
`payment-recorded.png`, `bank-transfer.png` and `payments-account.png`.

## Errors encountered and resolved

1. Site creation could not find `psql`: the previous image only contained the
   MariaDB command-line tools. Added the Postgres client.
2. A backup probe rejected the server/client version mismatch (server 16, client
   15). Installed `postgresql-client-16` and verified schema dumps on both engines.
3. The first fresh-site smoke fixture selected a group customer category, which
   cannot contain customers directly. The fixture now creates a leaf category.
4. The older payments-account HTTP check mocked only the helper, so its package
   session path attempted an outside request with a dummy fixture key and failed.
   It now uses the package fake and a transport guard; subsequent checks pass
   without network calls. No real API credential was used. The deployment key
   stayed empty throughout the trial.

5. The first sales-order rerun inherited an active `SO Edit Perm Workflow` from
   the earlier test run. `test_ordered_qty_is_reset_when_cancelled_sales_order_is_unlinked`
   then failed with a workflow-transition error on both databases. Resetting only
   the module's two workflow fixtures and clearing caches restored test isolation;
   neither the test nor upstream application code was changed.

The browser fixture was also adjusted for the pinned framework's `/desk` route,
per-app setup-completion flags, its initial empty invoice row, and invoice
rounding. These were walkthrough-fixture changes, not application patches.

## Running on Postgres

Docker Compose v2.20 or newer is required for database-file inclusion. Create
`.env` from `.env.example` if it does not already exist, then run:

```sh
ERP_DB=postgres ./start
```

The Administrator password is in `.runtime/local-admin-password`. Stop the
other local stack before switching engines. Existing data stays in its original
project volumes. To stop Postgres without deleting its data:

```sh
ERP_DB=postgres ERP_COMPOSE_PROJECT=erp-pg ERP_APP_IMAGE=erp-pg-app \
  docker compose --env-file .env -f docker/docker-compose.yml down
```

For checks, use a disposable site with `PRAMAAN_FAKE=1` and an empty
`PRAMAAN_API_KEY` in its environment. The checks create fixture records and must
not run on a real customer site. After starting that fake-only stack:

```sh
pg() {
  ERP_DB=postgres ERP_COMPOSE_PROJECT=erp-pg ERP_APP_IMAGE=erp-pg-app \
    docker compose --env-file .env -f docker/docker-compose.yml "$@"
}
pg exec -T app python -m unittest discover -s review
pg exec -T app node --test "erpnext/tests/js/**/*.test.mjs"
pg exec -T app python review/check_database.py
pg exec -T app python review/check_payment_account_framework.py
```

For the upstream subset, enable tests on the disposable site with the framework
CLI, warm the bootstrap module, and run the five module names in the results table
using `run-tests --lightmode --module`. The CLI working directory is
`/app/.runtime/bench/sites`; the command prefix is
`python -m frappe.utils.bench_helper frappe --site erp.localhost`.

## CI proof

`test-postgres` in `.github/workflows/ci.yml` starts local Postgres 16 and Redis
services, prepares the pinned runtime from the checkout, creates and migrates a
fresh site, and runs the seven database smoke checks, the payments-account HTTP
check, 96 Python unit tests and 10 JavaScript tests. The job has a 40-minute limit,
requires no secrets, and uses fake mode with an empty deployment key.

The initial support implementation (included in `ff0fc7e`) passed all eight run
commands verbatim on a `git archive HEAD` copy in a Linux container, reusing the
ERP runtime image rather than building another large image. Service hosts were changed to Docker service names instead of loopback;
Python, Node and client tools came from the prepared runtime. The image's
existing package cache was available. Total command time was **150.39 seconds**.
That archived run included 93 unit tests; the fake-link follow-up reran all 96
unit tests and the 128-test sales-order module on both databases. `actionlint`
passes. The hosted GitHub job has not run; nothing was pushed.

No new capability gaps or integration replacements were needed. The swap map
already keeps local MariaDB/Postgres, Redis, queues and workers as owned
infrastructure. The old `BLOCKED.md` was removed after rebuild authorization.
