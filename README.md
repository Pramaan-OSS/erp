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

## What to expect

- **Live today:** model calls, page reads, email sending, social sign-in.
- **Off today:** mailboxes, calendars, calling, bank feeds, company
  enrichment, and the rest of the optional lookups — they show a plain
  "not available yet" message instead of pretending to work.

## Built on

This template is built on [ERPNext](https://github.com/frappe/erpnext) by
Frappe Technologies, published under GPL-3.0. The original licence text is in
`LICENSE-ORIGINAL`, and this template carries the same notice under AGPL-3.0.
