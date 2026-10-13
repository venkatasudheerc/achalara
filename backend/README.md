# Portfolio Management System — Backend

A FastAPI backend for multi-client, multi-strategy investment portfolio management.

## Features

- **Client → Account → Sleeve hierarchy** — each sleeve is one strategy running in one account
- **Trade ingestion** — CSV upload or live Google Sheets sync (no credentials needed)
- **Position tracking** — open positions, closed round-trips, realized & unrealized P&L
- **Performance metrics** — MWR (IRR) and TWR (geometric linking) at sleeve / account / client / strategy level
- **Deduplication** — safe to re-import CSV or re-run a sync; duplicates are always skipped
- **Scheduler** — APScheduler daily Google Sheets sync via registered `SheetSyncConfig`

## Quick Start

```bash
cd backend
cp .env.example .env   # set DATABASE_URL at minimum

./infra.sh up -d       # start Colima → Docker → Postgres+Redis → migrations → app
./infra.sh status      # verify all layers
```

Swagger UI: `http://localhost:8000/docs`  
See [INFRA.md](INFRA.md) for the full runbook and [GETTING_STARTED.md](GETTING_STARTED.md) for a guided first run.

## API Endpoints

### Clients

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/clients/` | Create client |
| `GET`  | `/api/v1/clients/{client_id}` | Get client |
| `GET`  | `/api/v1/clients/{client_id}/performance` | Aggregated MWR/TWR across all sleeves (`?start_date=&end_date=`) |
| `GET`  | `/api/v1/clients/{client_id}/performance/monthly` | Month-on-month return breakdown |
| `GET`  | `/api/v1/clients/{client_id}/positions` | Merged positions across all sleeves |
| `GET`  | `/api/v1/clients/{client_id}/trades` | All trades with pagination (`?skip=0&limit=100`) |

### Accounts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/clients/{client_id}/accounts` | Create account |
| `GET`  | `/api/v1/clients/{client_id}/accounts` | List accounts |
| `GET`  | `/api/v1/clients/{client_id}/accounts/{account_id}` | Get account |
| `GET`  | `.../accounts/{account_id}/performance` | Aggregated MWR/TWR for the account |
| `GET`  | `.../accounts/{account_id}/performance/monthly` | Month-on-month return breakdown |
| `GET`  | `.../accounts/{account_id}/positions` | Merged positions across account sleeves |

### Sleeves

Sleeves are nested under `/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `.../sleeves` | Apply a strategy to an account (create sleeve) |
| `GET`  | `.../sleeves` | List sleeves |
| `GET`  | `.../sleeves/{sleeve_id}` | Get sleeve |
| `GET`  | `.../sleeves/{sleeve_id}/performance` | MWR/TWR (`?start_date=&end_date=`) |
| `GET`  | `.../sleeves/{sleeve_id}/performance/monthly` | Month-on-month return breakdown |
| `GET`  | `.../sleeves/{sleeve_id}/positions` | Open positions with unrealized P&L |
| `GET`  | `.../sleeves/{sleeve_id}/positions/closed` | Closed positions with realized gains |
| `GET`  | `.../sleeves/{sleeve_id}/trades` | Trade history with pagination |
| `POST` | `.../sleeves/{sleeve_id}/market-prices` | Manually update prices `{ "prices": { "AAPL": 189.5 } }` |
| `POST` | `.../sleeves/{sleeve_id}/fetch-market-prices` | Fetch prices from Webull |

### Strategies

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/strategies/` | Create a firm-wide strategy definition (409 on duplicate name) |
| `GET`  | `/api/v1/strategies/` | List all strategies |
| `GET`  | `/api/v1/strategies/{strategy_id}` | Get strategy |
| `GET`  | `/api/v1/strategies/{strategy_id}/performance` | Roll-up MWR/TWR across all sleeves for this strategy |
| `GET`  | `/api/v1/strategies/{strategy_id}/performance/monthly` | Month-on-month return breakdown |

### Trades

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/trades/` | Create a single trade (requires `sleeve_id`) |

### Admin

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/admin/import-historical` | Import trades from CSV upload (`?mode=VALIDATE\|IMPORT&client_id=...`) |
| `POST` | `/api/v1/admin/sync-daily` | Sync trades from a public Google Sheet |
| `GET`  | `/api/v1/admin/sync-logs` | Import/sync audit logs |
| `POST` | `/api/v1/admin/sync-configs` | Register a sheet → sleeve mapping for daily auto-sync |
| `GET`  | `/api/v1/admin/sync-configs` | List sync configs (`?client_id=` to filter) |
| `PATCH`| `/api/v1/admin/sync-configs/{config_id}` | Enable/disable a sync config |
| `DELETE`| `/api/v1/admin/sync-configs/{config_id}` | Remove a sync config |

Full parameter details are in [../openapi.yaml](../openapi.yaml) and at `/docs`.

## Google Sheets Integration

The sync endpoints fetch any publicly shared Google Sheet without credentials.

**Sheet requirements:**
- Shared as "Anyone with the link can view"
- Header row with columns: `Date`, `Symbol`, `Action`, `Quantity`, `Price`, `Commission`, `Strategy`, `Account`, `Notes`
- `Date`: `YYYY-MM-DD` or `YYYY/MM/DD` — both accepted
- `Action`: `Buy`/`Sell` or `BUY`/`SELL` — case is normalized

**Example sync call:**

```bash
curl -X POST "http://localhost:8000/api/v1/admin/sync-daily" \
  -G \
  --data-urlencode "client_id=<your-client-id>" \
  --data-urlencode "sleeve_id=<your-sleeve-id>" \
  --data-urlencode "sheet_id=<your-google-sheet-id>" \
  --data-urlencode "range_name=Sheet1"
```

Re-running the same sync is safe — duplicate rows are skipped via `google_sheet_row_id`.

## CSV Import Format

```
Date,Symbol,Action,Quantity,Price,Commission,Strategy,Account,Notes
2025-03-17,ABC,BUY,40,25.00,0,Thematic ETFs,Taxable,Initial purchase
```

```bash
# Dry-run first
curl -X POST "http://localhost:8000/api/v1/admin/import-historical?client_id=<id>&mode=VALIDATE" \
  -F "file=@trades.csv"

# Then persist
curl -X POST "http://localhost:8000/api/v1/admin/import-historical?client_id=<id>&mode=IMPORT" \
  -F "file=@trades.csv"
```

Omit `sleeve_id` to let the importer auto-route rows by Account + Strategy columns.

## Testing

```bash
# All tests (no Docker needed — uses in-memory SQLite)
backend/venv/bin/pytest backend/tests -v

# With coverage
backend/venv/bin/pytest backend/tests --cov=backend/app

# Single file
backend/venv/bin/pytest backend/tests/test_sleeves.py -v
```

## Project Structure

```
backend/
├── app/
│   ├── api/
│   │   ├── routes/          # Thin route handlers
│   │   │   ├── clients.py
│   │   │   ├── accounts.py
│   │   │   ├── sleeves.py
│   │   │   ├── strategies.py
│   │   │   ├── trades.py
│   │   │   └── admin.py
│   │   └── schemas/         # Pydantic request/response models
│   ├── models/              # SQLAlchemy ORM models
│   │   ├── client.py
│   │   ├── account.py
│   │   ├── sleeve.py        # account × strategy join; owns trades/positions
│   │   ├── strategy.py
│   │   ├── trade.py
│   │   ├── position.py
│   │   └── sync_log.py
│   ├── services/            # Business logic
│   │   ├── performance_service.py
│   │   ├── mwr_calculation.py
│   │   ├── twr_calculation.py
│   │   ├── portfolio_calculation.py
│   │   ├── trade_ingestion.py
│   │   ├── trade_import.py
│   │   ├── google_sheets_sync.py
│   │   ├── daily_sync.py
│   │   ├── scheduler.py
│   │   ├── market_price.py
│   │   └── webull_market_data.py
│   ├── db/database.py       # Sync engine + SessionLocal
│   ├── main.py              # FastAPI entry point + lifespan
│   └── config.py            # Settings (reads .env)
├── migrations/              # Alembic migration scripts
├── tests/                   # pytest suite
├── bruno/                   # Bruno API collection
├── docker-compose.yml       # Postgres + Redis
├── infra.sh                 # Stack manager
├── openapi.yaml             # OpenAPI 3.0 spec
└── requirements.txt
```

## Environment Variables

```env
DATABASE_URL=postgresql://postgres:dev123@localhost:5432/pms_dev
REDIS_URL=redis://localhost:6379/0
WEBULL_APP_KEY=your_webull_key
WEBULL_APP_SECRET=your_webull_secret
SCHEDULER_ENABLED=true
PYTHON_ENV=development
LOG_LEVEL=DEBUG
```

## Development

```bash
black app/                   # format
flake8 app/                  # lint
alembic revision --autogenerate -m "description"   # new migration
alembic upgrade head         # apply migrations
```

See [DATA_MODEL.md](DATA_MODEL.md) for the authoritative schema reference.
