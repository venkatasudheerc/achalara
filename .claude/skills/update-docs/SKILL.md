---
name: update-docs
description: Bring Achalara's documentation up to date with the code. Use after any change to models, migrations, routes, jobs, schedules, settings, deployment or the md (market data) package, before committing or opening a pull request, or when asked to "update the docs" or check them for drift.
---

# Keep Achalara's documentation up to date

The docs are part of the change. A pull request that changes behaviour without changing the docs
that describe it is not done. Every doc below is in a **public** repository, except those marked
*(local)*: everything in `docs/` is git-excluded, so update those files when present and never
`git add` them.

## 1. Find what changed

```sh
git fetch mine main 2>/dev/null; git diff --stat mine/main...HEAD; git status --short
```

Read the diff itself, not only the file names. List each change in behaviour: new or changed
tables and columns, routes and their shapes, jobs and their times, settings, containers, rules,
limits, user-visible screens.

## 2. Map each change to its docs

| When this changes | Update |
|---|---|
| A model or migration (any schema) | `backend/DATA_MODEL.md`; for `md`, also `docs/MARKET_DATA.md` § 2 *(local)* |
| A route or its request/response | `openapi.yaml` (the contract test enforces it), then `cd frontend && npm run gen:api`; the router table in `backend/CLAUDE.md` if a prefix is new |
| A service's rule (performance, tax lots, sync, access, portal) | The matching section of `backend/CLAUDE.md` |
| `backend/app/md/**` (market data) | `docs/MARKET_DATA.md` *(local)* (plan status, design, schedule, Webull budget, troubleshooting, limitations); `backend/CLAUDE.md` § "Market data"; `backend/DATA_MODEL.md` § "The `md` schema" |
| A scheduled job or its time (`services/scheduler.py`, `md/schedule.py`) | `deploy/DEPLOY.md` § Routine; `docs/MARKET_DATA.md` § 5 *(local)* for md jobs; the System status notes in `backend/CLAUDE.md` |
| A setting in `app/config.py` | `deploy/.env.example` (name only, empty value) and `deploy/DEPLOY.md`; `backend/.env.example` if it exists |
| `deploy/**` (compose, Caddy, backup) | `deploy/DEPLOY.md` |
| A brokerage connector | `backend/app/connectors/CONNECTORS.md`, `backend/CLAUDE.md` § Brokerage Sync Rules |
| A frontend page, hook, route or design token | `frontend/CLAUDE.md` (Routing, Features, Shared components, Design Tokens) |
| A gap the frontend works around | `docs/OPEN_ITEMS.md` *(local)* |
| A table, relation or index anywhere | `docs/DATABASE_MODEL.md` *(local)* as well as `backend/DATA_MODEL.md` |
| An item done, found or deferred | `docs/OPEN_ITEMS.md` *(local)*: tick it off or add it, and its "Last updated" date |
| A phase finished or a plan changed | `ROADMAP.md`; for market data, the status table in `docs/MARKET_DATA.md` § 1 *(local)* |
| Start-up or developer commands | `backend/INFRA.md` (the one local runbook), `backend/CLAUDE.md` § Commands; `README.md` only if the quick start changes |
| A new doc | Add it to this table, and point to it from the nearest `CLAUDE.md` |
| A planned `md` table or column | `PLANNED_TABLES` in `backend/app/md/status_report.py`, which the Market data page lists as not built |

## 3. Edit

- **Check every statement against the code before writing it.** Read the constant, the cron
  trigger, or the message text, and quote it as it is: times, limits, counts, file names,
  status-page wording. Never describe intended behaviour as built.
- **Change only what is now wrong or missing.** Keep each doc's structure and voice: plain
  sentences, tables for comparisons, real file paths in backticks, no marketing words.
- Keep **status** and **limitations** honest. When something is built, move it from "Planned"
  to "Built". When a limitation is removed, delete it. When a change adds a limitation (a cap, a
  source that can refuse, something not handled), add it.
- If two docs say the same thing, keep the detail in one and point to it from the other.
- Remove text about anything that was deleted.

## 4. Nothing private (the repository is public)

Before saving any doc:

- **Invent every example.** Use tickers like `XYZ` and `AAA`, and round invented figures. Never
  use a real client's name, account number or last four, holdings, trades, quantities, prices,
  balances or returns, even from the dev database.
- **No secrets or personal contacts.** Leave out API keys, tokens, passwords, the SEC contact
  email, server IP addresses and personal email addresses. Settings are documented by **name**
  only (`SEC_CONTACT_EMAIL=`).
- Counts of public things are fine (index sizes, number of sectors). Counts derived from client
  data are not (how many securities clients hold).
- Action items, private notes and anything about specific people go in the local-only
  `docs/OPEN_ITEMS.md` or `docs/DATABASE_MODEL.md`. The whole `docs/` folder is listed in
  `.git/info/exclude` and never committed; check `git status` shows nothing under `docs/` staged.

Then scan the changed docs:

```sh
git diff -U0 -- '*.md' '*.yaml' '*.example' | grep -nEi '@[a-z0-9-]+\.[a-z]{2,}|[0-9]{1,3}(\.[0-9]{1,3}){3}|key=|token=|secret|password=' || echo "nothing found"
```

Look at every hit. Expected ones are `example.com`/`example.invalid` addresses and placeholder
names in `.env.example`.

## 5. Verify and report

- `backend/venv/bin/pytest backend/tests/test_openapi_contract.py -q` if routes changed.
- `cd frontend && npm run build` if `openapi.yaml` or frontend docs that name types changed.
- Report to the user:
  - which docs were changed, and in one line each, what was corrected or added;
  - anything found to be wrong but left alone, and why;
  - any statement that could not be checked against the code.

Do not commit, push or open a pull request unless asked. Ask before opening a pull request.
