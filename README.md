[![CI](https://github.com/Pramaan-OSS/erp/actions/workflows/ci.yml/badge.svg)](https://github.com/Pramaan-OSS/erp/actions/workflows/ci.yml)

# ERP

A complete, open-source ERP: accounting, orders, stock, manufacturing, buying,
selling, projects and more. Every outside service call goes through one
Pramaan connection, so a single `PRAMAAN_API_KEY` is all you configure.

## Quick start

```sh
cp .env.example .env      # paste PRAMAAN_API_KEY=... into .env
./start                   # builds and starts everything on http://localhost:18010
```

`./start` generates the local database password, the Administrator password
(written to `.runtime/local-admin-password`) and any other missing local
settings on first run. It needs Docker and nothing else. Without a key the app
still starts and shows one plain message where a service call would happen;
optional features (bank feeds, route planning, text messages, payment links,
address checks, shipping, company and tax lookups, document reading) stay off
until the service offers them for your account.

## Running on Postgres

Postgres 16 is optional; MariaDB remains the default. With Docker Compose v2.20
or newer, run:

```sh
ERP_DB=postgres ./start
```

This uses the separate `erp-pg` project and creates a fresh site. It does not
convert an existing MariaDB database. Stop the other local stack before
switching. See [POSTGRES.md](POSTGRES.md) for test results, limitations and
commands for running checks with the fake client.

## What to expect

- **Live today:** model calls, page reads, email sending, social sign-in.
- **Off today:** mailboxes, calendars, calling, bank feeds, company
  enrichment, and the rest of the optional lookups — they show a plain
  "not available yet" message instead of pretending to work.

## Built on

This template is built on [ERPNext](https://github.com/frappe/erpnext) by
Frappe Technologies, published under GPL-3.0. The original licence text is in
`LICENSE-ORIGINAL`, and this template carries the same notice under AGPL-3.0.

### Italian e-invoice submission (not yet live-verified)

With the existing Italy module enabled (System Settings country: Italy), an
administrator opens an Italian Company and chooses **Italian invoicing account**,
then saves the handle of the builder's existing connected invoicing account
(`conn_...`). Never enter the account's token here. The connection must belong to
the builder and be configured for the submitting Italian business. All requests use
`erpnext/pramaan.py` and the server's `PRAMAAN_API_KEY`.

Open a submitted Italian Sales Invoice or credit note and choose **Submit Italian
e-invoice**. ERP generates its private XML, estimates the request and shows the
actual document number, date, recipient, line quantities, unit prices and taxes.
Download the complete private XML from that confirmation dialog to review it, then
choose **Confirm submission**. Changing the invoice or selected account invalidates
the confirmation. Only single-body TD01/TD04 XML within the capability's limits is
supported; other document types remain available for local export.

**E-invoice status** checks the original submission with its original connected
account. Pending means queued. Accepted means exchange acceptance; receipt delivery
is shown separately and does not claim business acceptance or payment. A refused
send can be corrected and explicitly reviewed again with a new request key. An
uncertain or interrupted send keeps its document identity reserved and cannot be
resent, even after an account change. Inspect the connected account to reconcile
it; ERP never guesses a missing reference or retries a submission automatically.
XML already reserved for submission cannot be replaced or removed. Existing local
generation and export remain available for invoices without recorded submissions.

Local checks use `PRAMAAN_FAKE=1` with an empty key. The invoice fixture mode is
`PRAMAAN_FAKE_EINVOICE=pending` (default), `accepted`, `rejected`,
`delivery_unavailable`, `refused`, `uncertain`, `connection_required` or `unavailable`.
Run `python -m unittest discover -s review` for contracts; in a disposable prepared
site, `python review/check_italy_einvoice_framework.py` checks durable submission,
permission boundaries, original-account reads and retry rules. No live e-invoice
submission has been verified or authorized.
