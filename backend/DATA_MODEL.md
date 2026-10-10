# PMS Data Model

Current schema after the **Sleeve refactor** (migration `fe521b07fb54`). All primary keys are
`String(36)` UUIDs. Timestamps (`created_at`, `updated_at`) are timezone-aware via `BaseModel`.

## Hierarchy at a glance

```
Client ──< Account ──< Sleeve >── Strategy        (Sleeve = account × strategy instance)
                          │
                          ├──< Trade
                          ├──< Position
                          ├──< CashActivity
                          ├──< SheetSyncConfig
                          └──< WeeklyPortfolioSnapshot

Client ──< BrokerageConnection ──< BrokerageAccount ──> Account, Sleeve   (linked logins)

SyncLog                                            (standalone import/sync audit trail)
```

- A **Strategy** is a firm-wide *definition* ("Growth", "Income") — reusable across accounts
  and clients.
- A **Sleeve** is one strategy *as run in one account*. It's the join between `Account` and
  `Strategy`, and it owns trades, positions and sync configs.
- One Strategy → many Sleeves (same strategy across many accounts/clients).
- One Account → many Sleeves (an account runs several strategies).

## ER diagram

```mermaid
erDiagram
    CLIENT ||--o{ ACCOUNT : has
    ACCOUNT ||--o{ SLEEVE : has
    STRATEGY ||--o{ SLEEVE : "is run as"
    SLEEVE ||--o{ TRADE : has
    SLEEVE ||--o{ POSITION : has
    SLEEVE ||--o{ SHEET_SYNC_CONFIG : feeds
    SLEEVE ||--o{ WEEKLY_PORTFOLIO_SNAPSHOT : snapshots

    CLIENT {
        string id PK
        string name
        string email UK
    }
    ACCOUNT {
        string id PK
        string client_id FK
        string account_number
        string name
        string description
    }
    STRATEGY {
        string id PK
        string name
        text description
    }
    SLEEVE {
        string id PK
        string account_id FK
        string strategy_id FK
    }
    TRADE {
        string id PK
        string sleeve_id FK
        date trade_date
        string symbol
        string action
        numeric quantity
        numeric price
        numeric commission
        string google_sheet_row_id UK
    }
    POSITION {
        string id PK
        string sleeve_id FK
        string symbol
        string status
        numeric quantity
        numeric cost_basis
        numeric current_price
        numeric market_value
        numeric unrealized_gain
        numeric realized_gain
        numeric realized_gain_pct
        datetime closed_at
    }
    SHEET_SYNC_CONFIG {
        string id PK
        string sleeve_id FK
        string sheet_id
        string range_name
        bool enabled
        datetime last_synced_at
    }
    SYNC_LOG {
        string id PK
        string import_type
        string status
        int rows_processed
        int rows_success
        int rows_failed
        json error_details
    }
    WEEKLY_PORTFOLIO_SNAPSHOT {
        string id PK
        string sleeve_id FK
        date week_start_date
        float twr_period
        float twr_cumul
        float mwr_cumul
        float cost_basis
        float market_value
        float cash_in
        float cash_out
        float realized_gain
    }
```

## Tables

### `clients`
| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | uuid |
| name | String(255) | not null |
| email | String(255) | not null, **unique** |

Relationships: `accounts` (1→N, cascade delete).

### `accounts`
| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | uuid |
| client_id | String(36) FK→clients.id | not null, **ON DELETE CASCADE** |
| account_number | String(50) | nullable (e.g. "58168069") |
| name | String(255) | not null |
| description | String(500) | nullable |

Relationships: `client` (N→1), `sleeves` (1→N, cascade delete).

### `strategies`  *(firm-wide definition)*
| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | uuid |
| name | String(255) | not null; **unique case-insensitively** |
| description | Text | nullable |

Constraints: unique functional index `uq_strategy_name_lower` on `lower(name)` — "Growth"
and "growth" are the same definition. Relationships: `sleeves` (1→N). No
`account_id`/`client_id` — a strategy is global.

### `sleeves`  *(account × strategy instance)*
| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | uuid |
| account_id | String(36) FK→accounts.id | not null, **ON DELETE CASCADE** |
| strategy_id | String(36) FK→strategies.id | not null, **ON DELETE RESTRICT** |
| accounting_method | String(20) | not null, default `ROUND_TRIP`; `FIFO` for brokerage-linked sleeves |

`accounting_method` decides how SELLs are matched to BUYs when deriving positions:
`ROUND_TRIP` pairs equal quantities (strategy sheets record discrete round trips, and a SELL
with no equal-quantity BUY is ignored); `FIFO` consumes the oldest lots and splits them on a
partial sell, which real brokerage activity needs. A sleeve set mixing both is matched sleeve
by sleeve and rolled up per symbol.

Constraints: `UNIQUE(account_id, strategy_id)` — one sleeve per strategy per account.
`RESTRICT` on `strategy_id` prevents deleting a strategy definition that still has live
sleeves. Relationships: `account`, `strategy` (N→1); `trades`, `positions` (1→N, cascade).

### `trades`
| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | uuid |
| sleeve_id | String(36) FK→sleeves.id | not null, **ON DELETE CASCADE** |
| trade_date | Date | not null |
| symbol | String(50) | not null; wide enough for `NYSEARCA:VOO`-style prefixes |
| action | String(10) | not null; check `IN ('BUY','SELL')` |
| quantity | Numeric(18,8) | not null; check `> 0`; 8 dp holds fractional shares |
| price | Numeric(15,6) | not null; check `> 0` |
| commission | Numeric(15,6) | default 0 |
| notes | Text | nullable (broker descriptions are unbounded) |
| google_sheet_row_id | String(255) | **unique**; null for CSV-sourced trades |
| external_id | String(255) | indexed, nullable; **unique per sleeve** — see below |

`external_id` is the source-derived idempotency key from
`connectors/models.NormalizedTrade`, persisted so `UNIQUE(sleeve_id, external_id)`
enforces idempotency in the database rather than only in the ingesting process.
It is nullable: trades created directly through the API, and any predating the
column, have none. Dedup therefore accepts **either** identity — the
`external_id`, or the legacy `(date, symbol, qty, price)` tuple.

### `positions`
| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | uuid |
| sleeve_id | String(36) FK→sleeves.id | not null, **ON DELETE CASCADE** |
| symbol | String(50) | not null; tracks `trades.symbol` |
| status | String(10) | not null, default `OPEN`; `OPEN` or `CLOSED` |
| quantity | Numeric(18,8) | not null (0 for closed rows); tracks `trades.quantity` |
| cost_basis | Numeric(18,2) | not null (0 for closed rows) |
| current_price | Numeric(15,6) | nullable (persisted market price) |
| market_value | Numeric(18,2) | nullable |
| unrealized_gain | Numeric(18,2) | nullable (open positions only) |
| realized_gain | Numeric(18,2) | nullable (set on closed rows) |
| realized_gain_pct | Numeric(10,4) | nullable (set on closed rows) |
| closed_at | DateTime(tz) | nullable (date of the final sell-out) |
| last_updated | DateTime(tz) | set on persist |

No unique constraint on `(sleeve_id, symbol)`: a symbol can have one `OPEN` row plus
one or more `CLOSED` rows. Realized gain is computed by **quantity-matched round-trips** —
each SELL is paired with the earliest unmatched BUY of the **same symbol and same quantity**
within the sleeve (a sleeve is account × strategy, so matching is also scoped to one
strategy). Each matched pair is one `CLOSED` row with
`realized_gain = (exit - entry) * qty - commissions`. Any BUY left unmatched rolls up into
the `OPEN` position. A SELL with no matching BUY is ignored (out-of-scope data, not an error).
(Migration `8f45b7a41fcf`.)

### `sheet_sync_configs`
| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | uuid |
| sleeve_id | String(36) FK→sleeves.id | not null, **ON DELETE CASCADE** |
| sheet_id | String(255) | not null |
| range_name | String(100) | default "Sheet1" |
| enabled | Boolean | not null, default true |
| last_synced_at | DateTime(tz) | nullable |

Client is derived via `sleeve → account.client_id` (the old `client_id` column was dropped).

### `sync_logs`
| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | uuid |
| import_type | String(20) | "HISTORICAL", "DAILY" or "BROKERAGE" |
| status | String(20) | PENDING / IN_PROGRESS / SUCCESS / FAILED |
| rows_processed / rows_success / rows_failed | Integer | default 0 |
| error_details | JSON | nullable |
| started_at / completed_at | DateTime(tz) | nullable |

Standalone audit trail — no FK to the entity hierarchy.

### `weekly_portfolio_snapshots`
| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | uuid |
| sleeve_id | String(36) FK→sleeves.id | not null, **ON DELETE CASCADE** |
| week_start_date | Date | not null; always a **Monday** |
| twr_period | Float | nullable; modified-Dietz HPR for this single week |
| twr_cumul | Float | nullable; geometric-linked TWR from inception to this Monday |
| mwr_cumul | Float | nullable; IRR (holding-period) from inception to this Monday |
| cost_basis | Float | open-position cost basis at Monday close |
| market_value | Float | open-position market value at Monday close (last-trade price) |
| cash_in | Float | gross BUY notional during the week |
| cash_out | Float | gross SELL proceeds during the week |
| realized_gain | Float | net realized P&L from round-trips closed during the week |

Constraints: `UNIQUE(sleeve_id, week_start_date)` — one snapshot per sleeve per Monday.

**Write path:** upserted automatically after any trade write (`POST /trades`) or import/sync. Full rebuild available via `POST /admin/rebuild-snapshots`. The `WeeklySnapshotService` walks all Mondays from the sleeve's first trade date. Snapshots are stored per-sleeve; at read time `WeeklySnapshotService.returns_series()` aggregates across the requested sleeve set (account / client / strategy) using market-value weighting for TWR and MWR.

**Migration:** `afc155b89ef6_add_weekly_portfolio_snapshots`.

### `cash_activities`
| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | uuid |
| sleeve_id | String(36) FK→sleeves.id | not null, **ON DELETE CASCADE** |
| activity_date | Date | not null |
| type | String(20) | `DIVIDEND` / `INTEREST` / `FEE` / `WITHHOLDING` / `CONTRIBUTION` / `WITHDRAWAL` / `TRANSFER` / `OTHER` |
| symbol | String(50) | nullable — the security the money relates to |
| amount | Numeric(18,2) | signed; positive is cash received |
| notes | Text | nullable |
| external_id | String(255) | not null, indexed — source-derived idempotency key |

Constraints: `UNIQUE(sleeve_id, external_id)`.

Non-trade money movements. Performance is securities-only (no cash balance), so only some of
these are returns: `FEE` always, and `DIVIDEND` / `INTEREST` / `WITHHOLDING` when paid on a
symbol the sleeve set has traded. They enter MWR as cash flows and TWR/monthly returns via
`cash_out`. Contributions, withdrawals, transfers and income on untraded symbols (a settlement
fund's interest) are stored for audit and never counted. See `CashActivityService.income_flows`.

### `brokerage_connections`
| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | uuid |
| client_id | String(36) FK→clients.id | not null, **ON DELETE CASCADE** |
| source | String(50) | connector registry name, e.g. `snaptrade` |
| external_user_id | String(255) | the user id the login was linked under at the source |
| external_connection_id | String(255) | the source's id for the login |
| institution | String(255) | e.g. "Vanguard" |
| status | String(20) | `active` / `broken` / `deleted` |

Constraints: `UNIQUE(source, external_connection_id)`. One row per brokerage login. Holds
references only — no credentials and no secret (the Personal SnapTrade flow issues none).

### `brokerage_accounts`
| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | uuid |
| connection_id | String(36) FK→brokerage_connections.id | not null, **ON DELETE CASCADE** |
| external_account_ref | String(255) | the source's account id |
| name | String(255) | as reported by the brokerage |
| number_last4 | String(4) | nullable — only the last four characters are kept |
| account_id | String(36) FK→accounts.id | nullable, **ON DELETE SET NULL** — set when mapped |
| default_sleeve_id | String(36) FK→sleeves.id | nullable, **ON DELETE SET NULL** — where synced trades land |
| status | String(20) | `unmapped` / `mapped` / `ignored` |
| initial_sync_completed | Boolean | false while the source is still loading history |
| transactions_synced_through | Date | nullable — the source's own completeness watermark |
| last_synced_at | DateTime(tz) | nullable — gates the 24h-per-account sync limit |
| last_reconciled_at | DateTime(tz) | nullable |
| reconciliation | JSON | nullable — `{matched, drifted[], unmatched_sells, skipped_rows}` |

Constraints: `UNIQUE(connection_id, external_account_ref)`.

Every account discovered under a login, mapped or not — kept apart from `accounts` because one
login exposes several accounts and some are never brought in. The mapped `Account` may belong
to a **different client** than the connection: one person's login reaches accounts they only
act on as agent, so `connection.client_id` is who holds the login, not who owns each account. Mapping creates the `Account`
and a `FIFO` sleeve (default strategy "Unallocated"). Symbols can later be moved to other
sleeves of the same account (`POST /trades/reassign`); sync dedups across all of the account's
sleeves so moved trades are not re-imported.

## Performance roll-ups

Returns are computed by resolving a level to its set of sleeve ids and running one calc over
the **merged** trade stream (not by averaging child returns):

| Level | Sleeve set | Endpoint |
|---|---|---|
| Sleeve | `[sleeve_id]` | `GET /clients/{c}/accounts/{a}/sleeves/{s}/performance` |
| Account | all sleeves where `sleeve.account_id = a` | `GET /clients/{c}/accounts/{a}/performance` |
| Client | all sleeves where `sleeve.account.client_id = c` | `GET /clients/{c}/performance` |
| Strategy | all sleeves where `sleeve.strategy_id = s` | `GET /strategies/{s}/performance` |

Each returns `{ level, id, name, summary, timeseries, children }`.

### Weekly returns series

Persisted snapshots power a separate weekly TWR + MWR chart endpoint:

| Level | Endpoint |
|---|---|
| Sleeve | `GET /clients/{c}/accounts/{a}/sleeves/{s}/performance/returns-series` |
| Account | `GET /clients/{c}/accounts/{a}/performance/returns-series` |
| Client | `GET /clients/{c}/performance/returns-series` |
| Strategy | `GET /strategies/{s}/performance/returns-series` |

Each returns `{ level, id, series: [{ date, twr_cumul, mwr_cumul }] }` where values are decimal
fractions (0.05 = 5%). Supports optional `start_date` / `end_date` query params.
Rebuild all snapshots: `POST /admin/rebuild-snapshots` (pass `sleeve_id` to scope to one sleeve).

## Notes / known trade-offs

- **`strategies.name` is unique case-insensitively** (`uq_strategy_name_lower` on
  `lower(name)`). The auto-route CSV import and `POST /strategies` both resolve names
  case-insensitively, so "Growth"/"growth" map to one definition (first-seen casing is kept).
  `POST /strategies` returns 409 on a case-insensitive duplicate.
- **`UNIQUE(sleeve_id, external_id)` is the primary trade dedup** (multiple NULLs allowed, so
  API-entered trades are unaffected). `IngestionService` treats a matching `external_id` **or**
  a matching `(date, symbol, qty, price)` tuple as a duplicate, so trades without an
  `external_id` still dedup as before. Quantity and price compare as normalized `Decimal`s,
  not floats, so fractional share counts compare exactly.
- **Brokerage trades dedup on `external_id` alone.** For sources whose id is a complete
  identity (`snaptrade`), the legacy tuple is not consulted: it has no action, so it would drop
  one leg of a same-day buy and sell at one price, which real brokerage data contains.
- **Brokerage coverage gaps are counted, not hidden.** Option legs, splits/mergers/assignments,
  and rows with an unresolvable symbol are skipped by the connector and tallied per sync in
  `skipped_rows`; the resulting share-count differences appear in the account's reconciliation.
- **`google_sheet_row_id` is retained but no longer the dedup path** (sheet trades go through
  `external_id` like every other source); it stays available for a future row-id-keyed source.
- **Migration `fe521b07fb54` is Postgres-guarded** and preserves each old strategy id as its
  sleeve id so child FK values didn't need rewriting. SQLite/tests build from the models via
  `create_all`. The follow-up migration `95798c4a2a9a` adds the case-insensitive unique index
  on `lower(name)` (portable across Postgres and SQLite).
