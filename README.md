# Achalara

Investment portfolio tracking for a small advisory practice. It follows every trade through a
**Client → Account → Sleeve** hierarchy (a sleeve is one strategy run in one account), pulls
brokerage activity through SnapTrade, keeps a daily record of each account's value, and reports
money- and time-weighted returns, realised gains as the brokerage reports them, and an account PDF
report. Clients see their own accounts in a read-only portal. A separate market-data store keeps
securities, index membership and sectors.

## Where to read next

| You want to | Read |
|---|---|
| Understand the model and the rules every change follows | [CLAUDE.md](CLAUDE.md), then [backend/CLAUDE.md](backend/CLAUDE.md) and [frontend/CLAUDE.md](frontend/CLAUDE.md) |
| Run it on your machine | [backend/INFRA.md](backend/INFRA.md) |
| Run it on a server | [deploy/DEPLOY.md](deploy/DEPLOY.md) |
| Know the tables | [backend/DATA_MODEL.md](backend/DATA_MODEL.md) |
| Know the API | [openapi.yaml](openapi.yaml), or `/docs` on a running backend |
| Add a brokerage source | [backend/app/connectors/CONNECTORS.md](backend/app/connectors/CONNECTORS.md) |
| Call the API by hand | [backend/bruno/README.md](backend/bruno/README.md) |
| See what is built and what is next | [ROADMAP.md](ROADMAP.md) |

## Stack

| Part | Choice |
|---|---|
| Backend | FastAPI (sync handlers), SQLAlchemy 2.0 (sync `Session`), Pydantic v2 |
| Database | PostgreSQL 15, schemas `public`, `perf` (daily performance) and `md` (market data); Alembic, with a separate history for `md` |
| Jobs | APScheduler in the backend; a separate `md-worker` process for market data |
| Frontend | React 18, TypeScript, Vite, Tailwind, TanStack Query |
| Tests | pytest with in-memory SQLite (never reaches a third-party API); Black, Flake8 |

## Quick start

```bash
cd backend && ./infra.sh up -d     # Postgres + Redis, migrations, API on :8000
cd frontend && npm run dev         # app on :5173
backend/venv/bin/pytest backend/tests
```

The first run needs a virtual environment, a `.env` and an advisor login; see
[backend/INFRA.md](backend/INFRA.md).
