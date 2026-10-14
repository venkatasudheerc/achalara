# CLAUDE.md — Backend

This file provides guidance to Claude Code when working in `backend/`.
Read the root `../CLAUDE.md` first for shared context (project overview, Sleeve model, monorepo layout) and `./connectors/CONNECTORS.md` for universal brokerage connector guidance.

## Tech Stack

- **Framework:** FastAPI 0.104 (sync `def` handlers run in the threadpool)
- **ORM:** SQLAlchemy 2.0 with sync `Session` (never `AsyncSession`)
- **Migrations:** Alembic
- **Database:** PostgreSQL 15 (Docker); SQLite in-memory for tests (built via `create_all`)
- **Validation:** Pydantic v2
- **Scheduler:** APScheduler 3 (`BackgroundScheduler`), started/stopped in the lifespan hook; Redis 7 is the optional jobstore
- **Testing:** pytest + httpx `TestClient`
- **Linting:** Black, Flake8

UUID (`String(36)`) primary keys on all models. Timestamps are tz-aware via `BaseModel`.

## Commands

Run from the repo root (`Achalara/`). The venv lives at `backend/venv/`.

```bash
# Start infra (Postgres + Redis)
cd backend && docker-compose up -d

# Run the server (from backend/, with venv active)
uvicorn app.main:app --reload --port 8000      # Swagger UI at /docs

# Tests (offline by default — never hits a third-party API)
backend/venv/bin/pytest backend/tests -v
backend/venv/bin/pytest backend/tests --cov=backend/app          # with coverage
backend/venv/bin/pytest backend/tests/test_sleeves.py -v         # single file
backend/venv/bin/pytest backend/tests/test_performance.py::test_name -v   # single test

# Live API tests — opt-in only, read-only, need real credentials in .env
export SNAPTRADE_TEST_USER_ID=<the userId you linked>
backend/venv/bin/pytest backend/tests/integration -m live -v -s

# Google Sheets sync against a sheet you name (opt-in; no sheet id is kept in the repo)
export GOOGLE_SHEETS_TEST_SHEET_ID=<sheet id>
backend/venv/bin/pytest backend/tests/test_google_sheets.py -m live -v

# First advisor login (run from backend/, asks for a password)
python -m app.cli create-advisor --email you@example.com --name "Your Name"

# Year-end price of an index option (per share, as quoted), for its year-end mark
python -m app.cli set-price --symbol SPX271217P06000000 --date 2026-12-31 --close 312.40

# Post a signed test event to our own webhook address (reachability + signature)
python -m app.cli send-test-webhook --url https://example.com/api/v1/webhooks/snaptrade

# Market indices' daily bars, for research: load a downloaded file, then top up
python -m app.cli load-index-file --symbol SPX --file SP500_daily.csv --source some-name --replace
python -m app.cli load-index-history

# Migrations (run from backend/)
alembic upgrade head
alembic revision --autogenerate -m "description"

# Format / lint (from backend/)
black app/
flake8 app/
```

`backend/infra.sh` wraps common docker/db operations.

## Architecture

Request flow: **route → service → ORM model**. Routes are registered in `app/main.py`:

| Prefix               | Router                                                  |
| -------------------- | ------------------------------------------------------- |
| `/api/v1/clients`    | `clients`, `accounts`, `sleeves` (nested under clients) |
| `/api/v1/strategies` | `strategies` (firm-wide definitions)                    |
| `/api/v1/trades`     | `trades`                                                |
| `/api/v1/admin`      | `admin` (import, sync-daily, sync-logs, sync-configs)   |
| `/api/v1/auth`       | `auth` (sign-in, invite/reset links, users) and `/clients/{id}/account-access` |
| `/api/v1/portal`     | `portal` (a client's accounts read together: overview, positions, trades, realised gains, performance; CSV) |
| `/api/v1`            | `connections` (brokerage link, discover, map, sync, reconcile, webhook) |
| `/api/v1`            | `performance` (periods by grain, statistics, account report)            |

**Performance roll-ups** (`services/performance_service.py`): a level resolves to a _set of sleeve ids_, then one calc runs over the **merged** trade stream — returns are NOT averaged from child returns. Account = all sleeves in the account; Client = all sleeves under the client's accounts; Strategy = all sleeves for that strategy. Each response is `{ level, id, name, summary, timeseries, children }`.

### Key files

| File                                    | Purpose                                                                                 |
| --------------------------------------- | --------------------------------------------------------------------------------------- |
| `app/main.py`                           | App startup, router registration, lifespan (scheduler start/stop)                       |
| `app/config.py`                         | `Settings` reads `.env` (`database_url`, `redis_url`, `scheduler_enabled`, Webull keys) |
| `app/db/database.py`                    | Sync engine, `SessionLocal`, `get_db()` dependency                                      |
| `app/services/performance_service.py`   | Resolves sleeve sets and dispatches MWR/TWR calc                                        |
| `app/services/mwr_calculation.py`       | IRR solver (Money Weighted Return)                                                      |
| `app/services/twr_calculation.py`       | Geometric linking (Time Weighted Return)                                                |
| `app/services/portfolio_calculation.py` | Position tracking, weighted-avg cost basis, `persist_positions`                         |
| `app/services/tax_lots.py`              | Lot matching (FIFO / MinTax) and the brokerage's reading of each closed lot             |
| `app/services/trade_ingestion.py`       | Row validation + **duplicate detection** (intentional — do not skip)                    |
| `app/services/trade_import.py`          | CSV import pipeline (`import_type` param; `VALIDATE`/`IMPORT` modes)                    |
| `app/services/google_sheets_sync.py`    | Fetches public sheets via CSV export (no credentials)                                   |
| `app/services/daily_sync.py`            | Reusable sheet→DB sync (`run_daily_sync`, `run_all_enabled_syncs`)                      |
| `app/services/connection_service.py`    | Brokerage link/discover/map/reconcile + `sync_brokerage_account` (the one sync path)    |
| `app/models/perf.py`                    | The `perf` schema: daily valuation, holdings, prices, corporate actions                  |
| `app/services/performance_build_service.py` | Rebuilds reconstructed daily rows from trades, prices and cash; `dietz_factor`       |
| `app/services/daily_capture_service.py` | Captures the brokerage's holdings, cash and total as observed daily rows                 |
| `app/services/performance_stats_service.py` | Periods, account activity, drawdowns, risk — all read from daily rows                |
| `app/services/price_history_service.py` | Daily closes from Webull for held securities and benchmarks                             |
| `app/services/index_history_service.py` | Daily bars of the market indices (`index_bars`), for research only                        |
| `app/services/benchmarks.py`            | The one list of benchmarks a return may be compared with, and their closes              |
| `app/services/corporate_actions.py`     | Splits; `adjusted_trades` restates trades in today's shares on read                     |
| `app/services/report_service.py`        | The account performance report (HTML template → PDF)                                    |
| `app/services/cash_ledger.py`           | Cash balance on any date, worked back from the brokerage's reported balance             |
| `app/services/cash_activity_service.py` | Dividends/fees persistence + `income_flows` (which cash counts as returns)              |
| `app/services/trade_reassignment.py`    | Move a symbol's history between sleeves of one account                                  |
| `app/connectors/snaptrade_connector.py` | SnapTrade adapter: trades, cash activities, skipped-row tally                           |
| `app/services/status_service.py`        | The advisor's system status: jobs, brokerage accounts, data freshness, backup, warnings |
| `app/services/run_log.py`               | In-memory record of job runs and recent warnings since the app started                  |
| `app/services/scheduler.py`             | APScheduler lifecycle (`start_scheduler`, `stop_scheduler`)                             |
| `app/services/market_price.py`          | Position price updates / persistence                                                    |
| `app/services/webull_market_data.py`    | Webull API client                                                                       |
| `app/services/live_quotes.py`           | Batched, briefly cached live prices for the portal's holdings screen                    |
| `app/models/sleeve.py`                  | The account × strategy join that owns trades/positions/sync configs                     |
| `app/models/sync_log.py`                | Standalone import/sync audit trail (no FK to the hierarchy)                             |
| `app/models/user.py`                    | Logins, sessions, one-time links, shared-account grants                                 |
| `app/services/auth_service.py`          | Sign-in, password rules, sessions, invites/resets, who may read which account           |
| `app/api/deps.py`                       | `get_current_user`, `require_advisor`, `require_access` (the rule on every data router) |
| `app/cli.py`                            | `python -m app.cli create-advisor` — the first advisor login                            |
| `app/services/portal_service.py`        | The client portal's views over every account a client may see, row by sleeve            |
| `tests/conftest.py`                     | Shared fixtures (DB session, `TestClient`)                                              |

## Coding Conventions

- **Routes are thin** — delegate all logic to a service; no business logic in handlers.
- **One service per domain.** Reuse existing services rather than duplicating logic.
- **Sync everywhere.** Plain `def` handlers + `Session`. Never add `async def` handlers that do blocking DB calls, and never mix in `AsyncSession`.
- **Pydantic schemas** live in `api/schemas/`; ORM models stay in `models/`.
- **Config via `.env`** through `config.py` — no hardcoded secrets/connection strings/API keys.
- **Schema changes go through Alembic** (`alembic revision --autogenerate`) — never edit tables directly.
- **Update `../openapi.yaml`** whenever an endpoint is added or its contract changes. `tests/test_openapi_contract.py`
  fails when the routes and the spec list different operations.

## Offline vs Live Tests

`pytest.ini` sets `addopts = -m "not live"`, so **the default run and CI never reach a
third-party API**. Tests that do are marked `@pytest.mark.live`, live in `tests/integration/`,
and additionally skip themselves unless real credentials are present — so they cannot run by
accident on a machine that lacks them.

- **Offline (default):** stub clients and recorded payloads. Deterministic, no network, no
  rate limit spent. Every mapping rule and dedup behavior is covered here.
- **Live (`-m live`):** answers only what offline tests cannot — what a real brokerage actually
  returns. Treated as exploratory, not regression cover: third-party payloads change outside
  our control, so asserting exact values there would make the suite flaky.

Live tests must stay **read-only**. Respect SnapTrade's limits (>=24h between transaction calls
per account, <=4 background holdings calls per user per day) — never loop them.

## Dedup Rules (don't bypass)

- **Sheet-sourced trades** dedup on `trades.google_sheet_row_id` (unique; NULL for CSV trades).
- **CSV imports** dedup on `(date, symbol, qty, price)` per sleeve in the import pipeline.
- Re-running a sync is safe — duplicates are skipped. The dedup in `trade_ingestion.py` is intentional.

## Sync Logic Must Stay Shared

The `admin/sync-daily` route and the scheduler job both call `run_daily_sync()` from `daily_sync.py`. Do not inline sync logic in routes or duplicate it in the scheduler.

## Sign-in and Access Rules

- **Every data router is mounted with `dependencies=[Depends(require_access)]`** in `app/main.py`.
  A new router must be mounted the same way; only sign-in, the link routes and the SnapTrade
  webhook (`connections.public_router`) are open. Do not add per-handler role checks for data
  routes — extend `require_access`, so the rule stays in one place.
- An advisor may call anything. A client user may only `GET`, and only: `/clients/{their id}`
  roll-ups, an account they own or were granted (`account_access`) and everything beneath it, and
  benchmarks. The rule reads `client_id` / `account_id` from the path, so **a route that exposes
  client data must carry those path parameters** or it is advisor-only.
- Never return a full account number to a client user; use `auth_service.display_name` and
  `last_four`.
- **A link may be emailed** (`services/mailer.py`, Resend, when `RESEND_API_KEY` and `MAIL_FROM`
  are set): `AuthService.email_link` sends an unused link to the login's own sign-in email,
  never to an address in the request. The message carries the link and nothing about the
  client's accounts, and a failure is logged without the key, the address or the link. Tests
  cannot send mail: the autouse `no_real_mail` fixture leaves it unconfigured and fails any
  test that reaches `mailer._post`.
- **The invitation form is the one public write** (`invitations.public_router`,
  `services/invitation_service.py`): a visitor leaves name, email, phone and a note, all
  required, checked in `api/schemas/invitation.py` (a name of letters; an email whose domain
  receives mail, `services/email_domains.py`, which tests replace through the autouse `no_dns`
  fixture; 10 to 15 phone digits, not one digit repeated or a plain run; a note of at least 50
  characters in words). It guards itself: a per-sender and a per-day limit kept in memory, a
  hidden field (`website`) that marks a script, and no second row for an email still waiting.
  It always answers `202` the same way, so the reply says nothing about limits or what is on
  file. Where email is set up, a request counts only once the visitor confirms it through the
  one email sent to the address given (`POST /invitation-requests/confirm`, by a button press so
  a mail scanner cannot confirm it; 48 hours; only a digest of the token is kept). The adviser's list is under
  `/api/v1/admin/invitation-requests`. A waiting request is a "needs a look" line on System
  status, and so an alert, with no name in it.
- Passwords are scrypt hashes; session and link tokens are stored only as SHA-256 digests. Never
  log or return a stored hash.
- **The portal (`/api/v1/portal`) is the exception to the path rule.** Its routes carry no
  client id; `deps.portal_viewer` answers for the signed-in client, or for the client an advisor
  names in `as_client` (ignored from a client user). `PortalService` starts from
  `AuthService.accounts_for_client`, so nothing outside the viewer's accounts can be reached, and
  an `account_id` that is not in view is a 404.
- Portal rows are built **per sleeve**, so each can name its account and strategy. Positions
  come from the custodian's latest recorded holdings (`perf.daily_holding`) where they exist,
  cost included (`avg_cost`; the trade history's average is the fallback when the custodian
  gives none); options are added from trades, unpriced.
- **Home (`PortalService.home`) mixes two clocks on purpose.** Total value, the day's change,
  the allocation and the largest holdings are at live prices; this year's return, cash, income
  and deposits come from the daily record and run through `record_through`. `_matched` holds
  each sleeve's matched lots for the request, so positions, realised gains and Home's notes
  do the matching once between them.
- **The positions and home screens show live prices; nothing else does.** `PortalService.positions(live=True)`
  reprices each holding from `services/live_quotes.py`: one batched Webull request for every
  symbol in view, kept for a minute. Only the price is live. Quantity and cost stay the
  custodian's, a holding with no quote keeps the custodian's price (`price_source` says which),
  and the request never fails or waits on the source. Do not fetch prices one symbol at a time,
  and do not feed live quotes into Home, Performance or the `perf` schema: returns stay tied
  to the custodian's daily record.
- **The portal's activity list (`PortalService.activity`) is trades and cash rows together.**
  The custodian's moves between the cash and margin sides of one account (`_is_bookkeeping`)
  are left out, and a cash row's description goes through `_cash_detail`, which drops trace
  and account numbers. Do not return `cash_activities.notes` to a client as stored.
- Tests never reach Webull: the autouse `no_live_quotes` fixture replaces `live_quotes._fetch`,
  and a test that wants live prices hands them in there.
- Tests: the `client` fixture is signed in as an advisor by overriding `get_current_user`;
  `anon_client` goes through the real sign-in (see `tests/test_auth.py`).

## Performance: the `perf` schema

Performance over time lives in the Postgres schema `perf` (`app/models/perf.py`); new
performance tables go there, with `__table_args__ = (..., {"schema": "perf"})`. Read
`DATA_MODEL.md` § "The `perf` schema" before touching it. The rules that must hold:

- **The day is the only stored grain.** Do not add tables or columns for weeks, months,
  quarters, or client/strategy roll-ups. Derive them in `PerformanceStatsService` from
  `perf.daily_valuation`. Returns are chained through time and summed-then-computed across
  members, never averaged.
- **Observed days are fact.** `DailyCaptureService` records the brokerage's holdings, cash and
  total for the day (`basis = "observed"`). Nothing may overwrite an observed value; a rebuild
  refreshes only its flows, return and `is_provisional`.
- **Reconstructed days are disposable.** `PerformanceBuildService.rebuild_account` replaces
  them wholesale. After anything that changes trades, call
  `performance_build_service.rebuild_for_sleeves`.
- **Read trades through `corporate_actions.adjusted_trades`** in any calculation of positions,
  value or returns. It applies two things on reading and never changes a stored trade: splits,
  and the assignment rule below.
- **An assigned option's premium belongs to the shares** (`corporate_actions.assignment_adjustments`).
  The brokerage reports the option leaving at no price and the shares changing hands at the
  strike. Read that way: an assigned written put lowers the shares' cost by the premium, an
  assigned written call raises the sale proceeds, and the option itself closes with no gain or
  loss. This is how it is taxed and how the brokerage states cost. An **expired** option keeps
  its premium as its own gain. The rule is worked out across all sleeves of the account (option
  and shares usually sit in different ones), only when the delivery is on file in full, so the
  cash of the two legs together never changes. Trades made by the connector carry
  `Assignment:` / `Expired:` at the start of their notes (`option_event`).
- **A closed lot has two readings, and they must not be mixed** (`services/tax_lots.py`).
  `realized_gain` is what happened and is what performance, returns and totals read.
  `cost` / `proceeds` / `disallowed_loss` / `reported_gain` / `short_term_gain` /
  `long_term_gain` are what the brokerage reports: wash sales, the 60/40 split and year-end
  mark of index options, written options as short-term. These move gain between lots and
  years and never change cash, so nothing in the `perf` schema may read them; only the
  realised-gains screens do. Add a tax rule in `tax_lots.py`, never in a route or the portal.
- **Which lots a sale closes** is the account's `cost_basis_method` (`FIFO` or `MIN_TAX`), set
  to match the brokerage. The source gives days, not times: a same-day purchase is read as
  bought after the sale.
- **A year-end price for an index option is entered by hand** (`set-price`, stored as a
  `manual` row in `perf.daily_price`); no feed prices options. Without one the lot is left
  unmarked and says so. Never estimate it.
- **Webull closes are adjusted** (splits and dividends). Never multiply a past adjusted close by
  a share count directly; value through the build service's trade-price anchoring. The anchor
  belongs to one run of a holding: it is dropped when the quantity returns to zero, and a trade
  that was not at the market (an assignment delivery, a merger leg) never sets it.
- **Price history must cover the whole time a security was held, by any account.**
  `PriceHistoryService._covered` checks both ends of the span; a recent fetch alone does not
  make a series complete. The source serves about 1,200 daily bars, so nothing before roughly
  five years ago can be priced and is carried at its last trade.
- **`index_bars` (public schema) holds the market indices' own daily bars.** The `perf` schema
  is for client data, so market reference tables like this one go in `public`. Never read it
  in a valuation or a portfolio's own return. It may be chosen as a benchmark: an index level
  leaves dividends out, and every screen that offers one says so.
- **One list of benchmarks: `services/benchmarks.py`.** Funds (closes in `perf.daily_price`,
  dividends included) and indices (`index_bars`). Add a benchmark there, not on a screen; the
  portal's performance response carries the list (`benchmarks`) and takes the choice
  (`?benchmark=`), and `PerformanceStatsService` reads closes through `benchmarks.closes`.
- **One daily-return formula per basis:** `dietz_factor` at market, `realized_factor` at cost
  (both in `performance_build_service.py`). The realised basis is a way of *reading* the same
  rows (`daily_valuation.cost_value` in place of `securities_value`), never a second table.
- Existing performance endpoints read from the daily record when it exists and fall back to
  `TWRCalculationService.growth_at` / `MWRCalculationService.calculate_mwr` (from trades) when it
  does not. Keep both paths returning the same response shape.
- Account and client views include cash where a `CashLedger` exists; sleeve and strategy views
  are securities-only.
- No return is quoted when no money was ever invested (written options, shorts): `None`, not 0.

## Brokerage Sync Rules

- `sync_brokerage_account()` in `connection_service.py` is the only brokerage sync path. The
  `/brokerage-accounts/{id}/sync` route, the scheduler job and the webhook handler all call it.
- At most one transactions pull per account per 24h. The guard lives in the service; only a
  source-initiated webhook passes `force=True`. Never loop or retry on a 429.
  The daily job runs at 8am US Eastern and is not held to that guard: it is once a day by its
  schedule, and a sync by hand the afternoon before must not cost the next morning's run. If the
  source refuses, the account is reported as `rate_limited` and tried again the next day.
- **Webhooks** (`connections.public_router`, `ConnectionService.handle_webhook`): the
  signature is checked over the event written with sorted keys and no spaces, as the source
  documents, or over the bytes as sent. An event id seen before (`run_log.first_delivery`) is
  answered `duplicate`, so a redelivery never spends a second pull. The daily job skips an
  account pulled in the last `SCHEDULED_SKIP_WINDOW`, which is one a webhook has just had
  pulled. Every event received is noted with `run_log.note_webhook` for System status.
- Brokerage sleeves use `accounting_method = "FIFO"`. Do not ingest brokerage trades into a
  `ROUND_TRIP` sleeve, and keep one trade source per sleeve.
- Sync dedups across **all sleeves of the account** (`dedup_sleeve_ids`), because symbols can
  be reassigned to other strategy sleeves after ingestion.
- **Mergers are read as trades** (`snaptrade_connector._to_merger_trade`): shares taken for cash
  are a sale at the cash per share; shares exchanged for shares are legs priced afterwards by
  `corporate_actions.carry_exchange_costs` so the cost carries across, and the lot matching
  moves the lots themselves to the new shares, opening dates included, with nothing closed
  (`PortfolioCalculationService._share_exchanges`, paired across the account's sleeves); a
  change of ticker (the same symbol leaving and arriving on one day) is dropped. Their notes start
  with `MERGER_NOTE`, which is how the rebuild knows they were not at a market price.
- **Fees on a stock sale** are the gap between the quoted value and `amount`: Vanguard reports
  `fee` as zero. `rederive` brings the fees of trades already on file up to date.
- Splits are recorded from the brokerage's rows by `corporate_actions.record_splits`, with the
  ratio worked out in the shares of the split's own day.
- Rows the connector still cannot represent are skipped **and counted**
  — never dropped silently. Every fetched row, skipped or not, is stored verbatim in
  `brokerage_activities`; use `ConnectionService.rederive` to re-read them before spending
  another pull.
- A synced trade goes to the sleeve already holding its symbol, else the sleeve routed for its
  `security_type` (`brokerage_accounts.sleeve_routes`), else `default_sleeve_id`. Do not place
  one symbol in two sleeves of an account.
- **One brokerage account is brought in once**, however many logins reach it (an owner's and an
  agent's). The source gives each login its own ids for the account, so
  `ConnectionService.duplicate_of` goes by `account_fingerprint` (brokerage + full number):
  `map_account` refuses a `same` match and wants `confirmed_distinct` for a `likely` one
  (brokerage + last four). A second client sees the account through `account_access`, never
  through a second mapping. The hint names another client's account, so it is sent to
  advisors only.
- **A new link belongs to the client whose page started it.** Every link sits under one identity
  at the source, so `discover` sees them all whichever client it is run for; `start_link`
  stamps `clients.brokerage_link_started_at` and `discover` files a link seen for the first
  time under that client, falling back to the client asked about only when none started one.

## System status

`GET /api/v1/admin/status` (`StatusService`) is what the advisor's System status page shows.
Its `attention` list is the plain-language summary of what needs a person; add a new check
there, not on the screen. A scheduled job must be wrapped in `run_log.tracked("<job id>")` and
listed in `status_service.JOBS`, or the page cannot show it. The record of runs and warnings is
in memory and starts empty at each restart. The backup's result comes from a file the server's
`deploy/backup.sh` writes into `STATUS_DIR`.

**Alerts leave the app** (`services/alerts.py`, a Telegram bot when configured), so they carry
only the wording `StatusService` marks as safe: a "needs a look" line that names a client or an
account must be added with an `alert=` twin that does not. Never log the bot token; it is part
of the address the message is posted to.

A brokerage link's state is only as fresh as the last time the source was asked.
`ConnectionService.check_links` asks (every six hours, and from the page's "Check now") and
records `status_checked_at` and `disabled_at`; the stored `status` alone can be days out of date.

## What "Done" Looks Like

- Route returns real data, not a placeholder or empty list
- A corresponding test exists and passes (`backend/venv/bin/pytest backend/tests`)
- Edge cases handled in the service layer (empty results, zero positions, etc.)
- No TODO/FIXME comments remain
- Any schema change has an Alembic migration, `DATA_MODEL.md` is updated, and `../openapi.yaml` is updated
