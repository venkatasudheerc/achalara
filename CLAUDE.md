# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@backend/CLAUDE.md
@frontend/CLAUDE.md

## Project Overview

**Achalara** is a multi-client, multi-strategy investment portfolio management system for advisory firms. It tracks trades through a `Client → Account → Sleeve` hierarchy, calculates portfolio performance (MWR/TWR), imports historical trades from CSV or Google Sheets, and fetches live prices via Webull.

See `ROADMAP.md` for what is built and what is next, and `backend/INFRA.md` to run it locally.

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
├── README.md              # what Achalara is, and where to read next
├── ROADMAP.md             # built, next, deferred, technical debt
├── docs/                  # local only, never in GitHub (the folder is git-excluded)
│   ├── OPEN_ITEMS.md      # action items, and gaps the frontend works around
│   ├── DATABASE_MODEL.md  # the full database model, indexes, performance concerns
│   ├── MARKET_DATA.md     # market data plan, design, running it, limitations
│   ├── idea.md            # the original vision
│   └── archive/           # superseded write-ups, e.g. the architecture review of 2026-10-11
├── backend/
│   ├── CLAUDE.md          # backend-specific guidance (read before touching backend code)
│   ├── app/               # FastAPI application
│   ├── migrations/        # Alembic migrations
│   ├── tests/             # pytest suite
│   ├── bruno/             # Bruno API collection
│   ├── INFRA.md           # running it locally: first run, start/stop, troubleshooting
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
- **Every change is checked for its impact, backend and frontend.** Every change or bug fix is
  checked for cross impacts across the backend, and every backend change is carried through to
  the frontend (types, hooks, screens, every role and state), in the same change. Run the
  `check-impact` skill (`.claude/skills/check-impact/SKILL.md`) before `update-docs` and before
  any commit; the pull request says what was checked under "Impact".
- **Docs move with the code.** Before committing a change in behaviour, run the `update-docs` skill
  (`.claude/skills/update-docs/SKILL.md`): it maps each kind of change to the docs that describe it.
- **A new setting follows the settings beside it.** Before adding one, read how its neighbours are
  set in `deploy/.env.example`, `deploy/docker-compose.yml` and `config.py`, and do it the same way.
  `.env` holds only first-hand values (a user name, a password, a key); anything built from them,
  such as a database address, is built in `docker-compose.yml` (as `DATABASE_URL` is from
  `POSTGRES_USER` and `POSTGRES_PASSWORD`), never stored beside its parts. A credential is a name
  and a password, listed together with the other logins. A value used in more than one place (a
  login's name in a script, a migration and compose) is one setting with a default, never the same
  literal written in each.

## Git and pull requests

- Work on a branch, push it to the `mine` remote, never to `main`; a ruleset makes `main`
  pull-request only, and only Sai merges. Ask before pushing a branch or opening a pull request.
- **Before every push to a branch with a pull request, check that it is still open:**
  `gh pr view <number> --json state -q .state`. Once it is `MERGED` or `CLOSED`, commits pushed to
  that branch reach nobody. Put the follow-up on a new branch from the latest `main`
  (`git fetch mine && git switch -c <new> mine/main`, then `git cherry-pick` the commits) and open a
  new pull request.
- After a pull request is opened, tell Sai about every further commit pushed to it before it is
  merged, so it is not merged without them.
- One concern per branch. Run the full backend suite (and `npm run build` for frontend changes)
  on the branch as it will merge, then scan for private data before pushing (`update-docs` § 4).
