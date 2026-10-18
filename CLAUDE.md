# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@backend/CLAUDE.md
@frontend/CLAUDE.md

## Project Overview

**Achalara** is a multi-client, multi-strategy investment portfolio management system for advisory firms. It tracks trades through a `Client → Account → Sleeve` hierarchy, calculates portfolio performance (MWR/TWR), imports historical trades from CSV or Google Sheets, and fetches live prices via Webull.

See `ROADMAP.md` for the phased plan.

## Starting the full stack

```bash
# Terminal 1 — backend infra + server
cd backend && docker-compose up -d
source venv/bin/activate && uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend dev server
cd frontend && npm run dev          # http://localhost:5173

# Regenerate typed API client after any openapi.yaml change
cd frontend && npm run gen:api      # copies ../openapi.yaml → src/api/schema.d.ts
```

## Monorepo Layout

```
Achalara/
├── CLAUDE.md              # this file — shared context
├── openapi.yaml           # OpenAPI 3.0 spec — source of truth for the API contract
├── README.md              # project overview and quick start
├── ROADMAP.md             # phased delivery plan
├── idea.md                # original vision
├── docs/
│   └── MARKET_DATA.md     # local only (git-excluded): market data plan, design, running it, limitations
├── backend/
│   ├── CLAUDE.md          # backend-specific guidance (read before touching backend code)
│   ├── app/               # FastAPI application
│   ├── migrations/        # Alembic migrations
│   ├── tests/             # pytest suite
│   ├── bruno/             # Bruno API collection
│   └── ...
└── frontend/
    ├── CLAUDE.md          # frontend-specific guidance (read before touching frontend code)
    └── ...                # React + TypeScript app (Phase 5)
```

**`openapi.yaml` at the root is the contract between frontend and backend.** The backend exposes it at `/docs`; the frontend generates a typed API client from it. Never duplicate endpoint definitions — update `openapi.yaml` when the backend API changes.

## The Sleeve Model (most important concept — applies to both layers)

Read `backend/DATA_MODEL.md` before touching models, performance calculations, or any UI that displays portfolio data. The hierarchy is:

```
Client ──< Account ──< Sleeve >── Strategy        (Sleeve = account × strategy instance)
                          ├──< Trade
                          ├──< Position
                          └──< SheetSyncConfig
```

- A **Strategy** is a firm-wide *definition* ("Growth", "Income") — global, reusable, no `account_id`/`client_id`. Names are unique case-insensitively; `POST /strategies` returns 409 on a duplicate.
- A **Sleeve** is one strategy *as run in one account* — the join between `Account` and `Strategy`. Sleeves own trades, positions, and sync configs. `UNIQUE(account_id, strategy_id)`.
- Trades/positions reference `sleeve_id`. Client is derived via `sleeve → account.client_id`.

This hierarchy must be reflected consistently in both the backend API routes and the frontend navigation / data-fetching logic.

## Cross-Cutting Conventions

- **No hardcoded secrets** anywhere — backend uses `.env` via `config.py`; frontend uses env vars via Vite's `import.meta.env`.
- **All IDs are UUIDs** (string, 36 chars). Never assume numeric IDs.
- **Timestamps are tz-aware** ISO-8601 strings in API responses.
- **`openapi.yaml` is the single source of truth** for request/response shapes. If you add or change an endpoint, update `openapi.yaml` too.
- **Docs move with the code.** Before committing a change in behaviour, run the `update-docs` skill
  (`.claude/skills/update-docs/SKILL.md`): it maps each kind of change to the docs that describe it.
