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

# Google Sheets sync against a sheet you name (opt-in; no sheet id is kept in the repo)
export GOOGLE_SHEETS_TEST_SHEET_ID=<sheet id>
backend/venv/bin/pytest backend/tests/test_google_sheets.py -m live -v

# First admin login (run from backend/, asks for a password)
python -m app.cli create-admin --email you@example.com --name "Your Name"

# Year-end price of an index option (per share, as quoted), for its year-end mark
python -m app.cli set-price --symbol SPX271217P06000000 --date 2026-12-31 --close 312.40

# Add what a custodian's activity report holds that is not on file (shows only; --apply writes)
python -m app.cli import-vanguard-report --account 5678 --file customActivityReport_12345678.xlsx

# Market indices' daily bars, for research: load a downloaded file, then top up
python -m app.cli load-index-file --symbol SPX --file SP500_daily.csv --source some-name --replace
python -m app.cli load-index-history

# Migrations (run from backend/)
alembic upgrade head
alembic revision --autogenerate -m "description"

# Market data's migrations are a separate history (migrations_md/)
alembic -n md upgrade head
alembic -n md revision --autogenerate -m "description"

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
| `/api/v1/portal`     | `portal` (a client's accounts read together: accounts, overview, positions, trades, realised gains, performance; CSV; the client's own account groups) |
| `/api/v1`            | `performance` (periods by grain, statistics, account report)            |
| `/api/v1/research`   | `research` (market insights from `md`, for every signed-in user; read-only) |

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
| `app/services/connection_service.py`    | The shared ingest of a feed's or a file's rows (`ingest_batch`) and the holdings reconciliation |
| `app/services/plaid_refresh_service.py` | The daily Plaid refresh: transactions, balances, holdings; records the day before         |
| `app/services/account_health.py`        | Each account's record: complete, provisional or incomplete, and where to download from    |
| `app/models/perf.py`                    | The `perf` schema: daily valuation, holdings, prices, corporate actions                  |
| `app/services/performance_build_service.py` | Rebuilds reconstructed daily rows from trades, prices and cash; `dietz_factor`       |
| `app/services/opening_position.py`      | What an account held before its history: worked back, stored as opening trades           |
| `app/services/daily_capture_service.py` | `record`: stores the institution's holdings, cash and total for a day as observed rows   |
| `app/services/performance_stats_service.py` | Periods, account activity, drawdowns, risk — all read from daily rows                |
| `app/services/price_history_service.py` | Daily closes from Webull for held securities and benchmarks                             |
| `app/services/index_history_service.py` | Daily bars of the market indices (`index_bars`), for research only                        |
| `app/services/benchmarks.py`            | The one list of benchmarks a return may be compared with, and their closes              |
| `app/services/corporate_actions.py`     | Splits; `adjusted_trades` restates trades in today's shares on read                     |
| `app/services/report_service.py`        | The account performance report (HTML template → PDF)                                    |
| `app/services/cash_ledger.py`           | Cash balance on any date, worked back from the brokerage's reported balance             |
| `app/services/cash_activity_service.py` | Dividends/fees persistence + `income_flows` (which cash counts as returns)              |
| `app/services/trade_reassignment.py`    | Move a symbol's history between sleeves of one account                                  |
| `app/services/vanguard_report.py`       | Reads Vanguard's activity report; plans and adds only the rows not on file               |
| `app/services/account_import_service.py` | Upload and import: the template, preview, import and the holdings check, for every door |
| `app/md/`                               | Market data (`md` schema): securities, index membership; its own worker (`app/md/worker.py`) |
| `app/md/read.py`                        | What the app may ask market data: the one way in from outside the package                |
| `app/md/insights.py`                    | Market insights and `TOOLS`, the registry the Research page and a future chatbot call     |
| `app/services/held_symbols.py`          | The symbols held, handed to market data so it never reads client data                     |
| `app/utils/symbols.py`                  | Every source's spelling of a ticker (`app_symbol`, `webull_symbol`, `figi_symbol`)        |
| `app/utils/webull_signing.py`           | Signing a Webull request, shared by the app's client and the market-data jobs            |
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
| `app/cli.py`                            | `python -m app.cli create-admin` — the first admin login                            |
| `app/services/portal_service.py`        | The client portal's views over every account a client may see, row by sleeve            |
| `app/services/account_kind.py`          | An account's kind (taxable, retirement, kids, cash), read from the brokerage's account name |
| `app/services/account_group_service.py` | A client's own named groups of accounts ("My groups")                                    |
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

Live tests must stay **read-only** and never loop a third-party API.

## Dedup Rules (don't bypass)

- **Sheet-sourced trades** dedup on `trades.google_sheet_row_id` (unique; NULL for CSV trades).
- **CSV imports** dedup on `(date, symbol, qty, price)` per sleeve in the import pipeline.
- Re-running a sync is safe — duplicates are skipped. The dedup in `trade_ingestion.py` is intentional.

## Sync Logic Must Stay Shared

The `admin/sync-daily` route and the scheduler job both call `run_daily_sync()` from `daily_sync.py`. Do not inline sync logic in routes or duplicate it in the scheduler.

## Sign-in and Access Rules

- **Every data router is mounted with `dependencies=[Depends(require_access)]`** in `app/main.py`.
  A new router must be mounted the same way; only sign-in, the link routes and the
  invitation form are open. Do not add per-handler role checks for data
  routes — extend `require_access`, so the rule stays in one place.
- **Three roles** (`models/user.py`). An **admin** is the platform's super user and may call
  anything. An **advisor** manages the clients assigned to them (`clients.advisor_id`): anything
  under such a client, the client list and the list of logins (each answered with their own
  clients only), creating a client (it becomes theirs), adding or moving trades in their clients'
  sleeves (`/trades/*` checks the sleeve), the strategies' definitions and the shared reference
  data; never `/admin/*` or strategy performance. Only an admin creates an advisor
  (`POST /auth/advisors`) or assigns one to a client. A **client** may only `GET`, and only:
  `/clients/{their id}` roll-ups, an account the guardrails let them see and everything beneath
  it, and the shared reference data. The rule reads `client_id` / `account_id` from the path, so
  **a route that exposes client data must carry those path parameters** or it is staff-only.
  `AuthService.manages` is the one test of whether an admin or advisor may act for a client.
- **Who sees which accounts is decided by guardrails**, in one place
  (`AuthService.accounts_for_client`), from `clients.spouse_id` and `guardian_id`: (1) everyone
  sees what they own; (2) spouses see each other's accounts except those the owner marks private
  (`accounts.is_private`, `PATCH /portal/accounts/{id}`, owner only); (3) a minor's guardian and
  the guardian's spouse see every account of the minor, which a minor cannot hide; (4) a minor sees
  only their own; (5) anything else only when shared (`account_access`). A spouse pair is kept on
  both sides; a minor has no spouse and cannot add anyone. An admin or advisor sets these
  (`PUT /clients/{id}/spouse`, `/guardian`, `POST /clients/{id}/relatives`); a client adds and
  invites their own spouse or minor (`/portal/relatives`). There is no "household" in the model or
  on screen.
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
  client id; `deps.portal_viewer` answers for the signed-in client, or for the client an admin
  (any client) or advisor (their own) names in `as_client` (ignored from a client user). `PortalService` starts from
  `AuthService.accounts_for_client`, so nothing outside the viewer's accounts can be reached, and
  an `account_id` that is not in view is a 404.
- **Any portal view can be narrowed to a set of accounts** (`account_ids`, repeated): the route
  calls `PortalService.narrow`, which keeps only those accounts in `visible` before anything is
  read, so every method answers for that set unchanged. An id out of view is a 404, as for
  `account_id`. The landing page uses this for a person, a kind or a group of accounts.
- `GET /portal/accounts` gives each account's owner's name, its **kind** (`account_kind.py`,
  from the brokerage's account name: taxable, retirement, kids, cash; a name that says nothing is
  taxable), its **value now** (`PortalService.live_values`, worked out exactly as the Holdings
  view's account tile: holdings at live prices, options and cash as the custodian last reported
  them, so the rail and the tile always agree), the custodian's last reported total
  (`recorded_value`) and cash with its day (`as_of`, the last *observed* row), and its source and
  last sync (`brokerage_accounts`). Bank, card, loan and property kinds come with Plaid.
- **Account groups are the one thing a client changes in the portal** (`/portal/groups`). The
  portal router is not behind `require_access`; its guard is `portal_viewer`, so the routes guard
  themselves: a group belongs to the viewer's client, members must be accounts in view, and an
  admin or advisor previewing (`as_client`) sees and may change them exactly as the client can: a
  preview is what the client sees.
- Portal rows are built **per sleeve**, so each can name its account and strategy. Positions
  come from the custodian's latest recorded holdings (`perf.daily_holding`) where they exist,
  cost included (`avg_cost`; the trade history's average is the fallback when the custodian
  gives none); options are added from trades, unpriced. A later observed day with no holdings
  listed (an account of options and cash) means it holds none (`PortalService._recorded`): never
  fall back to the list before it. Options are valued together at the custodian's figure: its
  securities total less the holdings it listed (all of it when it listed none and our records
  show no shares).
- **Home (`PortalService.home`) mixes two clocks on purpose.** Total value, the day's change,
  the allocation and the largest holdings are at live prices; this year's return, cash, income
  and deposits come from the daily record and run through `record_through`. `_matched` holds
  each sleeve's matched lots for the request, so positions, realised gains and Home's notes
  do the matching once between them.
- **The positions and home screens, and the accounts list's `value`, show live prices; nothing else does.** `PortalService.positions(live=True)`
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
  `performance_build_service.rebuild_for_sleeves`. An account a feed reports on each day is
  rebuilt only up to its last observed day: the next morning's record says what the days after
  were, and a rebuilt day would value written options from their last trade, far from market.
  An account with no daily report is rebuilt to the last market day.
- **An account opens at what it held before its history** (`services/opening_position.py`).
  A feed's history reaches back only so far (Plaid two years at most), so
  `rebuild_account` first calls `OpeningPositionService.refresh`: each security's shares before
  the first transaction are worked back from the institution's latest recorded holdings (a day
  the transactions are complete through, `transactions_synced_through`; tried with and without
  that day's own trades, as a day's holdings can be taken before its trades show), and the cash
  from the ledger. They are stored as **opening trades**, a buy per security on the market day
  before the first transaction, priced at the institution's cost where nothing since changed it,
  else that day's market price, with notes starting `OPENING_NOTE` and ids `OPENING_ID_PREFIX`.
  That day is the record's first, with nothing moved in and no return, so what was already
  there is the opening value, never a gain (`PerformanceStatsService._opening` reads a first
  day with no money moved as the opening). Opening trades are **derived, never fact**: refresh
  deletes and works them out again every time, so history added later (a sync, a file) moves or
  removes them, and it re-runs the reconciliation from the stored holdings when they change.
  Never create or edit one elsewhere. The activity lists, the import's matching and the sync's
  duplicate check leave them out (`NOT_OPENING`); positions, cost basis, the holdings check and
  the ledger count them. **Nothing is guessed:** a security working back below zero shares, or
  cash below zero in an account not owed money, means a transaction is missing; the account
  opens empty, as before, and the reason is logged.
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
- **A cash account earns only its income.** For an account whose kind is cash-like
  (`CASH_LIKE`: cash, checking, savings and the owed kinds, `account_kind.py`), `rebuild_account` counts every change in the day's balance, less its
  interest, dividends, fees and tax withheld (`_cash_account_income`), as money in or out. The
  transfers on file are not used for it: for a bank-style account they can be missing or dated a
  day or two from the balance they moved, and the gap would read as a gain or a loss.
- No return is quoted when no money was ever invested (written options, shorts): `None`, not 0.

## Feeds and files

**A fresh start (2026-11-14).** SnapTrade is retired and nothing it brought in is kept: the
migration `d1e5c3a8b2f6` removes every client, client login, account and everything recorded for
them when the deploy starts the backend (advisor logins, strategies, prices, recorded splits,
market data and invitation requests stay). Clients and accounts are then added afresh: accounts
through Plaid (below), their earlier history from the custodian's own files.

- `ConnectionService.ingest_batch` is the one way rows reach an account, from a feed or a file:
  kept verbatim in `brokerage_activities`, routed to the account's sleeves, deduplicated across
  them (`dedup_sleeve_ids`, since symbols can be moved between sleeves), then splits, positions
  and the daily record brought up to date.
- A trade goes to the sleeve already holding its symbol, else the sleeve routed for its
  `security_type` (`brokerage_accounts.sleeve_routes`), else `default_sleeve_id`. Do not place
  one symbol in two sleeves of an account. Feed sleeves use `accounting_method = "FIFO"`.
- Rows a reader cannot represent are skipped **and counted**, never dropped silently, and every
  row is stored verbatim.
- **A custodian's own file brings the history** (`services/vanguard_report.py`, through
  `services/account_import_service.py`). The account's owner (`POST /portal/accounts/{id}/imports`)
  or the advisor (`POST /clients/{client_id}/accounts/{id}/imports`) uploads Vanguard's activity
  report (Excel or CSV) or Achalara's template (`frontend/public/achalara-activity-template.csv`).
  A `…/imports/preview` call shows what would change and writes nothing. A row counts as on file
  on its economics, never on ids: side, quantity, price within a cent a share, on the same day
  and symbol; else within two weekdays; else under another spelling of the symbol; an expiry or
  assignment matches its own contract only; cash matches on amount within 3 days. Sweeps and
  same-day transfer pairs between the account's cash and margin sides are not activity. Added
  rows are stored under ids starting `vanguard:` (`REPORT_ID_PREFIX`), and ingestion recognises a
  Plaid trade or cash row that matches one, so a day is never counted twice. **One holdings
  check** (`AccountImportService.holdings_check`) compares every day the custodian recorded
  holdings with what the trades add up to and says which differ, when they last agreed and first
  differed, and where a report should start (`download_from`). Options and "~" names are not
  compared. It is asked before an upload (`GET …/imports/check`), shown after one, and read by
  System status and the account's health. The file itself is never kept. A shared account takes
  no uploads. An admin or advisor previewing a client (`as_client`) sees and may use exactly what the
  client does.
- **Splits and mergers are read from the custodian's file** (`vanguard_report.read_rows`). A
  "Stock split" row (the shares it added) is kept as a `SPLIT` source row whose `payload.units`
  `corporate_actions.record_splits` turns into a ratio, worked out in the shares held just before
  on its own day; a split already recorded for that symbol and day is on file. A "Corp Action
  (Merger)" row is a trade noted `MERGER_NOTE`: shares taken for cash are a sale at the cash per
  share; a leg of an exchange for other shares is recorded at no price and
  `corporate_actions.carry_exchange_costs` carries the cost across (lot moves in
  `PortfolioCalculationService._share_exchanges`). A merger row with no symbol takes the symbol
  another row of the report gives the same company. A merger leg on file matches its row whatever
  its price, since carrying the cost changed it. **Plaid's splits and mergers are not read yet**:
  none has been seen in real data; the account's health flags the difference until one is.

## Linking with Plaid

A client adds their own accounts through Plaid (`connectors/plaid_connector.py`,
`connectors/plaid_reader.py`, `services/plaid_link_service.py`, routes under
`/portal/links/plaid`). One developer account (`PLAID_CLIENT_ID`, `PLAID_SECRET`) serves every
client; each login a client links is a `brokerage_connections` row with `source = "plaid"` and
its accounts are `brokerage_accounts` rows. Rules:

- **The access key is stored only encrypted** (`access_token_enc`, `utils/secret_box.py`, key
  `PLAID_TOKEN_KEY`). Never log it, return it, or keep it anywhere else.
- **An account's identity is its own id; a link is Plaid's ids.** Institution and last four
  (Plaid's `mask`, the real last four) are clues, never unique. `account_fingerprint` is not set
  for Plaid: it needs the full number, which Plaid does not give for investments.
- **Matching needs evidence and a person.** Candidates are only the client's own and shared
  accounts. "same" needs exactly one candidate agreeing on institution and last four *and* on
  holdings (symbol by symbol) or the observed balance to the cent; agreeing on less is "choose";
  nothing is "new". Nothing is linked until `confirm`.
- **Two feeds never write to one account.** Linking an account another link already feeds is
  refused (409): a second Plaid login gives the same transactions ids of its own, so it would
  count them twice. Repairing a login that needs signing in again is to come (update mode).
- **What Plaid sends is read by `plaid_reader`**: buys and sales moved from settlement back to
  the trade day; holdings valued at each security's `close_price` (Plaid's holding price is a
  day late) with the total moved to match; same-day internal transfer pairs and sweeps are not
  activity; bank and card rows are money in or out, with interest and bank fees their own
  types. A card's or loan's balance is stored negative (`account_kind.OWED`), so totals are net
  worth.
- **Every link asks for two years of transactions** (`TRANSACTION_DAYS`, Plaid's most). Plaid
  gives 90 days otherwise, and it can only be asked for when a login is linked.
- **The plan's limit:** every Plaid login ever linked counts (`PLAID_MAX_LOGINS`, the trial's
  10); `start` refuses at the limit and the dialog warns when two or fewer are left.
- A feed records an account's day through `DailyCaptureService.record` (holdings with their
  prices, cash, total), which reconciles and rebuilds.
- **The daily refresh** (`services/plaid_refresh_service.py`, job `plaid_refresh`, 6:30 AM US
  Eastern Tuesday to Saturday) records the **day before** for every mapped account: an
  early-morning balance is where the previous day ended, so a weekend's movements land in
  Monday's record and no recorded day is rewritten. Bank and card rows come through
  `/transactions/sync` from the login's `transactions_cursor`, saved only once all it handed
  back is on file; a changed row is changed in place and a removed one (or one gone back to
  pending) is deleted, both by Plaid's id. Investment transactions are read again over the last
  `REFRESH_DAYS`. A login Plaid says needs signing in again (`NEEDS_SIGN_IN`) is set `broken`
  and skipped until repaired; one failing login never stops the rest.
- **Repairing a login** (`PlaidLinkService.repair_start` / `repaired`, routes
  `/portal/links/plaid/{id}/repair` and `/repaired`): Plaid Link opens in update mode for the
  same login (a link token made with its access key), so no new place on the plan is used and its
  transaction ids, and so its history, carry on. Afterwards Plaid is asked whether the login reads
  again; if so it is `active` again and refreshed at once. Only the login's owner can repair it.
  `/portal/accounts` says which accounts wait on it (`needs_sign_in`, and `login_id` for the
  owner); the Dashboard asks the owner to sign in again and tells anyone else whose login it is.
- Tests never reach Plaid: they pass a fake client to `PlaidLinkService` / `PlaidRefreshService`.

## How far a record can be trusted

`services/account_health.py` gives every account one state, on `/portal/accounts` as `health`:
**complete**, **provisional** (a difference in the last `SETTLE_DAYS` that may clear as
transactions post) or **incomplete** (a transaction is missing), with plain reasons and
`download_from`. Three checks feed it: the opening (`reconciliation["opening_problems"]`,
written by `OpeningPositionService.refresh`), the holdings check, and `cash_check`, which compares
each day the institution recorded cash with what the history works back to. The record is worked
back from today, so the latest day always agrees and an earlier day that differs means a movement
after it is missing; every day before it is out by that amount, so **an opening is never worked
back through a cash difference**. The rail marks an incomplete account, the Dashboard says which
to repair and from when, and System status lists it (alert wording names no account). Nothing
here changes a figure; **no nudge may be built on an account that is not complete.**

## Market data: the `md` schema

Reference data about securities and indices (`app/md/`, `DATA_MODEL.md` § "The `md` schema"),
separate from client data in `public` and `perf`. Plan, design, operation and limitations:
`../docs/MARKET_DATA.md` (the `docs/` folder is local only, not in the repository). Rules:

- **Current vs history.** A current table has one row per thing; a `_hist` table holds dated rows.
  Write both in the same transaction; a current table must always be rebuildable from its history.
- **Its jobs run only in the market-data worker** (`python -m app.md.worker`, the `md-worker`
  container), never in the web process or its scheduler. Each run goes through
  `md.jobs.tracked_run` (a Postgres advisory lock and a `md.job_run` row) and is listed in
  `md.schedule.MD_JOBS`, which System status reads. The worker never runs migrations.
- **Keep every fetched file** in `md.source_file` before reading it, so a reader can be fixed and
  the files read again.
- **Never apply a file that looks wrong**: outside the index's member range, or older than what is
  on file. Report it and leave membership as it was.
- **Nothing in `perf` reads `md`, now or later**; returns and valuations are untouched by market
  data. The app keeps its own prices in `perf.daily_price` and `md` will hold its own. Neither
  reads the other, and the two are never mixed in one calculation.
- **Keep `md` able to run on another machine.** No foreign keys or SQL joins between `md` and
  `public` or `perf`. Outside the package, import only `app.md.read` and `app.md.schedule` (the CLI
  is the exception); inside it, only `app.md` and `app.utils`. `worker.py` alone also opens the app's database, to hand
  `seed_securities` the list from `held_symbols`. `tests/test_md_separation.py` holds all this. A
  client screen that needs `md`'s data reads a small copy the app owns, refreshed by a job; it never
  depends on `md` being reachable. System status reads `md` through `read.py` and says so if it
  cannot (`MdUnavailable`).
- **`md` stands on its own:** it opens sessions through `md.database.MdSession` (`MD_DATABASE_URL`
  when set, the app's database otherwise), reads its settings from `md.config` (the same `.env`
  names, never `app.config`), and its tables use `md.base.MdModel`, in their own metadata, not the
  app's `Base`. A new `md` setting goes in `md/config.py`; a new `md` table extends `MdModel`.
- **`md` has its own migrations** (`migrations_md/`, run with `alembic -n md ...`). Its version
  table is inside the schema, so a dump of `md` carries it. A new `md` table goes there, never in
  `migrations/`. The backend applies both histories at start.
- **The model holds any market (`md.market`); every securities feed is American** (index levels also
  include Indian indices, in rupees; no Indian security is collected). A ticker is unique within a
  market, so a lookup by ticker must name one: today's jobs filter on `US_MARKET`. A security belongs
  to one market and has its own `currency`. Price tables key on the security and record the currency.
  Returns and tax lots have no currency handling, so nothing foreign may reach `perf`.
- **Daily closes (`md/closes.py`, `md.price_daily_hist`) are prices as traded, never adjusted,** and
  a day on file is never overwritten. Each close is dated by its own last trade (`last_trade_time`,
  Eastern), and a close from a day not yet over (before 5 PM Eastern) is not stored. Webull's daily
  bars are forward-adjusted with no option to turn that off, so these cannot be fetched later.
  Who is priced: every US security ever in an index (it stays priced after leaving) and every
  tracked fund (`md.tracked_fund`, `md-track-fund`). Snapshot requests take 100 symbols and one
  category; a symbol Webull does not know refuses the whole request (`WebullInvalidSymbols`), so
  it is dropped and the request repeated.
- **Adjusted history (`md/adjusted.py`, `md.price_adj_daily`) is what every return reads:** Webull's
  daily bars, adjusted for splits and dividends (a total return), about five years deep. When the
  source rewrites a series, the window is fetched again and older days on file are rescaled by the
  same factor; never mix these with prices as traded (`price_daily_hist`).
- **Index levels in `md` (`md/levels.py`, `md.index_level_hist`)** come from the Yahoo feed the app
  uses (`utils/yahoo_chart.py`, shared); a level is a price return, and every result says its basis.
  **One list of indices: `levels.INDEX_LEVELS_INFO`** (code, Yahoo symbol, name, country,
  currency, group, volatility); `LEVELS` is derived from it, and `/api/v1/research/indices` serves
  it to the page, so add an index there only, and only if Yahoo serves its history. It holds the
  US indices and 21 NSE indices (Nifty 50, Nifty 500 as Yahoo's `^CRSLDX`, Nifty Financial
  Services as `NIFTY_FIN_SERVICE.NS`, India VIX…). An index is **shown and asked for with a
  leading `^`** (`^SPX`, `^NSEI`) and **stored without it**: `performance.series` treats `^X` as
  the index always, and plain `X` as a security first, then an index; the Market data page
  flags an index code that is also a ticker. Results say what an index is
  (`insights._subject_notes`): an `INR` level is a return in rupees, before currency moves; a
  volatility index (VIX, India VIX) is expected volatility, never called a return or a gain.
  **Each market runs on its own clock** (`levels.MARKET_CLOCK`): a US close is final after 5 PM
  New York time, an Indian one after 4:30 PM IST. The US indices are fetched by
  `md_index_levels` (9:15 PM and 6:15 AM Eastern); the Indian ones by `md_index_levels_in`, on
  weekdays at 6:00 PM in Asia/Kolkata time (`schedule._india_levels_trigger`), so US clock
  changes never move it. `md-index-levels --market US|IN` runs one; without it, both. Volatility indices stay out of the Overview's stock indices.
  Yahoo is free and unofficial: an index can stop arriving while the run still succeeds, so
  `levels.stale_levels` names any index with no new level for more than 4 weekdays (or none at
  all) on the Market data page and on System status, and so in the alerts.
- **Returns are computed, never stored by period,** with `utils/returns.py` (shared with the
  portfolio figures: ISO weeks, calendar months, a period from the last close before it). Ad-hoc SQL
  uses `md.day_return` (a view) and `md.week_return` / `md.month_return` (materialized, refreshed by
  `md_refresh_returns`). `md/performance.py` answers the API (`/api/v1/research/returns`,
  `seasonality`, `consistent-months`, `movers`), reading `md.month_return` on Postgres for questions
  across many stocks. A group's figures use today's members and say so (`survivorship`).
- **Index data is never pruned.** A history limit may apply only to stock and ETF prices in `md`.
- **The app and `md` spell tickers differently** (`BRK B`, `BRK.B`). Convert through
  `utils/symbols.py`; Webull answers `INVALID_SYMBOL` to `BRK.B`. Once `symbol_aliases` exists,
  match them only through it, never by comparing the text. Its upkeep job scans every table that
  stores symbols, so a new table that stores symbols must be added to the scan. Do not rewrite
  stored trades to match.
- **Tests never reach the network**: replace `md.sources.fetch` with the test's files. In SQLite
  the `md` schema maps to the default one (`tests/conftest.py`), so `md` table names must not
  repeat a `public` or `perf` table name.
- **Webull from market-data jobs goes through `md.webull.WebullClient`**: paced per endpoint at
  about half the lowest documented limit (fundamentals 30 a minute, others 120), outside 8:30 AM to
  6:00 PM Eastern on weekdays. A 429 raises `WebullRefused`: stop that part of the job for the run;
  never retry in a loop. Requests are counted into `md.job_run.requests`.
- **The SEC needs a contact email** (`SEC_CONTACT_EMAIL`); without it SEC lookups are skipped.
  Never write that address into a tracked file.
- Sectors are the 11 GICS sectors (`md.sector`). Precedence for sector: manual > iShares > Webull
  industry's sector > SEC code; for industry: manual > Webull > SEC. A Webull industry's sector is
  worked out from its index members (`ishares_majority`), not written by hand.
- By hand: `python -m app.cli md-index-membership`, `md-identifiers [--names-only]`, `md-classification
  [--refresh]`, `md-daily-closes`, `md-adjusted-history`, `md-index-levels`, `md-refresh-returns`,
  `md-track-fund [--symbol XYZ --group gold] [--remove]`, `md-track-fund --file app/md/tracked_funds.txt [--apply]` (the list of tracked funds; each ticker is checked with Webull first, so a typo never becomes a security, and nothing changes without `--apply`), and `md-set-sector --symbol XYZ --sector IT --industry "…"` (never overwritten).
- **The Market data page (`/app/market-data`)** reads `GET /api/v1/admin/market-data/status`
  (`app/md/status_report.py`, through `read.market_data_status`): jobs, indices, coverage, tables and
  what is not built, with its own `attention` list. It is advisor-only, because the counts include
  symbols from holdings. A planned table goes in `PLANNED_TABLES` and leaves the list by itself once
  its model exists. A new `md` job only needs adding to `MD_JOBS` to appear there.
- **Security names:** the identifiers job (`identifiers.fill_names`) names a security still called by
  its ticker from its SEC company, else Webull's instrument name, and index files rename one the
  same way (`membership._security_for`). A real name is never replaced. Trademark marks (®, ™) are
  dropped. `md-identifiers --names-only` reads only Webull's instrument list (one request per page)
  to name securities still called by their ticker, without the SEC and FIGI lookups.

### Research and chatbot guardrails

Research (`/api/v1/research`, the Research page) and the planned chatbot read market data and
must never change anything. Two independent layers hold this; keep both.

- **Research reads `md` only through `md.database.ReadSession`.** Its engine makes every
  transaction read-only (`default_transaction_read_only=on`; `PRAGMA query_only` in SQLite) and
  connects as `MD_READ_DATABASE_URL` when set: the `md_reader` login, which has `SELECT` on the
  `md` schema and no rights at all on `public` or `perf`. On the server `docker-compose.yml` builds
  that address from `MD_READER_USER` (default `md_reader`) and `MD_READER_PASSWORD`; the script and
  the grants migration read the same name, so never write the name into code. Unset, or with no password in it, it uses `md`'s own
  URL, still read-only (`MdSettings.read_url`). Every function in `read.py`'s research section opens it through `_read()`.
- **Never use `MdSession`, `SessionLocal`, `get_db` or an engine** in `md/performance.py`,
  `md/insights.py` or `api/routes/research.py`, and never join client data into research.
  `tests/test_research_guardrails.py` scans for this and checks a write is refused.
- **`md_reader` is created by hand once per server** (`deploy/create-md-reader.sh`, password
  `MD_READER_PASSWORD` in `deploy/.env`, never in the repository). The `md` migration
  `c6a9d4e2f8b1` grants it `SELECT` and default privileges, so a new `md` table is readable
  without a new grant. Never grant it a write.
- **One registry: `insights.TOOLS`.** Each entry is a name, a description, JSON Schema parameters
  (`additionalProperties: false`) and a function; `GET /api/v1/research/tools` serves the list. A
  chatbot calls only these, never free SQL, and has no write path. A new insight is a function
  here plus a route, whose answer carries its basis (`total` or `price`), its sample (years or
  days) and `notes` in plain words; no advice wording.
- **Access:** research is shared reference data (`_SHARED_READ_PREFIXES` in `deps.py`): any
  signed-in user may `GET` it, nothing else. The Market data job page
  (`/api/v1/admin/market-data/status`) stays advisor-only.

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

A Plaid login's state is as fresh as its last morning refresh, which records
`status_checked_at`, and `disabled_at` when Plaid says the login needs signing in again. Each
account with an incomplete record is a "needs a look" line (`account_health`).

## What "Done" Looks Like

- Route returns real data, not a placeholder or empty list
- A corresponding test exists and passes (`backend/venv/bin/pytest backend/tests`)
- Edge cases handled in the service layer (empty results, zero positions, etc.)
- No TODO/FIXME comments remain
- Any schema change has an Alembic migration, `DATA_MODEL.md` is updated, and `../openapi.yaml` is updated
