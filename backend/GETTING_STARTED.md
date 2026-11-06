# Getting Started — Portfolio Management System

## Prerequisites

- Python 3.10+
- Docker & Docker Compose (for PostgreSQL + Redis)
- Git

## Quick Start

### Step 1: Navigate to the backend directory

```bash
cd "/Users/sai/Documents/Github 2/Achalara/backend"
```

### Step 2: Set up the environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set DATABASE_URL at minimum
```

### Step 3: Start the full stack

```bash
./infra.sh up -d
```

This starts Colima (if needed) → Docker → Postgres + Redis → runs Alembic migrations → starts the app on port 8000.

Check all layers are healthy:

```bash
./infra.sh status
```

### Step 4: Open API Documentation

Visit **http://localhost:8000/docs** — Swagger UI with all endpoints ready to test.

---

## Testing the API

### Create a Client

```bash
curl -X POST "http://localhost:8000/api/v1/clients/" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Fund", "email": "fund@example.com"}'
```

### Create a Strategy (firm-wide definition)

```bash
curl -X POST "http://localhost:8000/api/v1/strategies/" \
  -H "Content-Type: application/json" \
  -d '{"name": "Growth", "description": "Aggressive growth strategy"}'
```

### Create an Account (under the client)

```bash
curl -X POST "http://localhost:8000/api/v1/clients/<client_id>/accounts" \
  -H "Content-Type: application/json" \
  -d '{"name": "Taxable Brokerage"}'
```

### Create a Sleeve (apply strategy to an account)

```bash
curl -X POST "http://localhost:8000/api/v1/clients/<client_id>/accounts/<account_id>/sleeves" \
  -H "Content-Type: application/json" \
  -d '{"strategy_id": "<strategy_id>"}'
```

### Create a Trade (requires sleeve_id)

```bash
curl -X POST "http://localhost:8000/api/v1/trades/" \
  -H "Content-Type: application/json" \
  -d '{
    "sleeve_id": "<sleeve_id>",
    "trade_date": "2026-05-15",
    "symbol": "AAPL",
    "action": "BUY",
    "quantity": 100,
    "price": 150.50,
    "commission": 0,
    "notes": "Initial purchase"
  }'
```

---

## Running Tests

Tests use an in-memory SQLite database — no Docker needed:

```bash
# All tests
backend/venv/bin/pytest backend/tests -v

# With coverage
backend/venv/bin/pytest backend/tests --cov=backend/app

# Single file
backend/venv/bin/pytest backend/tests/test_sleeves.py -v
```

---

## Development Commands

```bash
black app/          # format
flake8 app/         # lint

# Database migrations
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic -n md upgrade head       # market data's own history (migrations_md/)
```

---

## Project Structure

```
backend/
├── app/
│   ├── api/
│   │   ├── routes/          # Thin route handlers
│   │   │   ├── clients.py
│   │   │   ├── accounts.py
│   │   │   ├── sleeves.py   # trades, positions, performance, market prices
│   │   │   ├── strategies.py
│   │   │   ├── trades.py
│   │   │   └── admin.py     # import, sync, sync-configs, sync-logs
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
│   ├── db/database.py       # Sync engine + SessionLocal
│   ├── main.py              # FastAPI entry point + scheduler lifespan
│   └── config.py            # Settings (reads .env)
├── migrations/              # Alembic scripts
├── tests/                   # pytest suite (SQLite in-memory)
├── bruno/                   # Bruno API collection for manual testing
├── docker-compose.yml       # Postgres + Redis
├── infra.sh                 # Stack manager
└── openapi.yaml             # OpenAPI 3.0 spec (import into Postman/Swagger)
```

---

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

---

## Stopping Services

```bash
./infra.sh down          # stop app + Docker containers
./infra.sh down -v       # also wipe Postgres data (fresh start)
```

---

## Troubleshooting

### PostgreSQL connection error

```bash
./infra.sh status        # check which layer is down
docker-compose up -d     # start Postgres + Redis directly
```

### Port 8000 already in use

```bash
lsof -i :8000
kill -9 <PID>
# or start on a different port:
uvicorn app.main:app --reload --port 8001
```

### Virtual environment issues

```bash
deactivate
source venv/bin/activate
pip install -r requirements.txt
```

---

## Success Checklist

- [ ] `./infra.sh status` shows all layers green
- [ ] `http://localhost:8000/docs` loads Swagger UI
- [ ] Can create a client, strategy, account, sleeve, and trade via the API
- [ ] `backend/venv/bin/pytest backend/tests -v` — all tests pass
