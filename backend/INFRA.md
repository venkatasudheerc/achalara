# Running Achalara locally

How to set up, start, stop, check and restart the stack on your own machine. Run everything from
`backend/`. For a server, see `../deploy/DEPLOY.md`.

## First run

Needs Python 3.10+, Node 18+ and a Docker runtime ([Colima](https://github.com/abiosoft/colima) on
macOS).

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # DATABASE_URL is already set for the Docker Postgres
./infra.sh up -d                   # containers, both migration histories, API on :8000
python -m app.cli create-advisor --email you@example.com --name "Your Name"   # asks for a password

cd ../frontend
cp .env.example .env               # VITE_API_BASE_URL=http://localhost:8000
npm install && npm run dev         # http://localhost:5173, sign in with the advisor login
```

Every data route needs a signed-in user, so call the API through the app, Swagger at `/docs` after
signing in, or the Bruno collection (`bruno/README.md`). Brokerage, market-data and mail keys in
`.env` are optional; without them those features say they are not configured.

> **TL;DR — use the wrapper:** `./infra.sh up -d` (start all), `./infra.sh status`,
> `./infra.sh down`, `./infra.sh restart`. Run `./infra.sh help` for all commands.
> The sections below document the raw commands the script wraps.
>
> **DB target:** `.env` `DATABASE_URL` points at the Docker Postgres
> (`postgresql+psycopg2://postgres:dev123@localhost:5432/pms_dev`), so the app and Alembic
> use the containerized Postgres. Tests still use in-memory SQLite (no infra needed).

## The stack has 4 layers

| Layer | What | Managed by |
|---|---|---|
| 1. Docker runtime | Colima VM (provides the Docker daemon on macOS) | `colima` |
| 2. Containers | `pms-db` (Postgres 15, port 5432), `pms-cache` (Redis 7, port 6379) | `docker-compose` |
| 3. Schema | Alembic migrations: the app's history (`public`, `perf`) and market data's (`md`) | `alembic`, `alembic -n md` |
| 4. App | FastAPI via uvicorn (port 8000) | `uvicorn` |

> Order matters: bring layers **up 1→4** and take them **down 4→1**. The app needs the DB; the DB needs the containers; the containers need Colima.

---

## Full stack — cold start

```bash
cd backend
source venv/bin/activate

colima start                       # 1. Docker runtime (no-op if already running)
docker-compose up -d               # 2. Postgres + Redis (detached)
alembic upgrade head               # 3. Apply migrations (idempotent — safe to re-run)
alembic -n md upgrade head         #    and market data's, which are a separate history
uvicorn app.main:app --reload --port 8000   # 4. App (foreground; Ctrl+C to stop)
```

Then open <http://localhost:8000/docs>.

## Full stack — shutdown

```bash
# 4. App: Ctrl+C in its terminal
docker-compose down                # 3+2. Stop & remove containers (DATA IS KEPT in the volume)
colima stop                        # 1. Stop the Docker VM (frees RAM/CPU)
```

`docker-compose down` keeps your data. To **wipe the database** (fresh start), add `-v`:

```bash
docker-compose down -v             # also deletes the postgres_data volume — DESTROYS all DB data
```

---

## Layer 1 — Colima (Docker runtime)

```bash
colima status        # is the VM running?
colima start         # start it
colima stop          # stop it
colima restart       # restart it
colima delete        # destroy the VM entirely (rare; full reset of the runtime)
```

If `docker` commands hang or say "cannot connect to the Docker daemon", the VM is down → `colima start`.

## Layer 2 — Containers (Postgres + Redis)

```bash
docker-compose ps            # status of pms-db and pms-cache
docker-compose up -d         # start (detached)
docker-compose stop          # stop without removing (keeps containers + data)
docker-compose start         # start previously-stopped containers
docker-compose restart       # restart both
docker-compose down          # stop AND remove containers (data volume kept)
docker-compose logs -f       # tail logs from both (Ctrl+C to exit)
docker-compose logs -f postgres   # just Postgres
```

Restart a single service:

```bash
docker-compose restart postgres
docker-compose restart redis
```

Health check (both should read `healthy`):

```bash
docker inspect --format '{{.State.Health.Status}}' pms-db
docker inspect --format '{{.State.Health.Status}}' pms-cache
```

## Layer 3 — Database (Alembic + psql)

```bash
alembic current              # current migration revision applied to the DB
alembic history              # list all migrations
alembic upgrade head         # apply all pending migrations (idempotent)
alembic downgrade -1         # roll back one migration
alembic downgrade base       # roll back everything (drops all app tables)
alembic -n md current        # the same commands with -n md act on market data's history
```

Open a psql shell inside the container:

```bash
docker exec -it pms-db psql -U postgres -d pms_dev
# inside psql:  \dt  (list tables)   \q  (quit)
```

One-off table check:

```bash
docker exec pms-db psql -U postgres -d pms_dev -c "\dt"
```

> Connection string used by the app and Alembic (from `.env` → `DATABASE_URL`):
> `postgresql+psycopg2://postgres:dev123@localhost:5432/pms_dev`
> (user `postgres`, password `dev123`, db `pms_dev` — defined in `docker-compose.yml`).

## Layer 4 — App (uvicorn)

```bash
# Foreground (dev, auto-reload):
uvicorn app.main:app --reload --port 8000

# Background (detached), logging to a file:
uvicorn app.main:app --port 8000 > /tmp/pms_uvicorn.log 2>&1 &

# Stop a backgrounded app:
pkill -f "uvicorn app.main:app"        # or: kill <pid>

# Status / quick checks:
curl -s http://localhost:8000/health   # {"status":"healthy",...}
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/docs   # 200
```

The scheduler starts and stops with the app when `SCHEDULER_ENABLED=true` (the default). It runs
the daily jobs System status lists: brokerage sync, daily capture, sheet sync, index history and the
link check. Locally you usually want `SCHEDULER_ENABLED=false`, so a run on your machine does not
spend a brokerage pull. Market-data jobs run only in their own worker (`python -m app.md.worker`),
never in the app.

---

## At-a-glance: is everything up?

```bash
colima status                                                   # VM
docker-compose ps                                               # containers
alembic current                                                 # schema revision
curl -s http://localhost:8000/health && echo                    # app
```

## Common situations

| Symptom | Fix |
|---|---|
| `Cannot connect to the Docker daemon` | `colima start` |
| `docker compose` → `unknown shorthand flag: 'd'` | Use the standalone binary: `docker-compose` (with a hyphen) |
| App boot: `ModuleNotFoundError: No module named 'apscheduler'` | `pip install -r requirements.txt` in the activated venv |
| App can't reach DB / `connection refused` on 5432 | Containers down → `docker-compose up -d`; wait for `healthy` |
| Port 8000 already in use | `uvicorn ... --port 8001`, or `lsof -i :8000` then `kill <pid>` |
| Want a clean database | `docker-compose down -v && docker-compose up -d && alembic upgrade head && alembic -n md upgrade head`, then `create-advisor` again |
| Tests don't need Docker | `pytest` uses in-memory SQLite — runs without any of the above |
| Virtual environment confused | `deactivate`, `source venv/bin/activate`, `pip install -r requirements.txt` |

## Loading trades by hand

Brokerage accounts sync themselves. For anything else, the Imports page takes a CSV and registers
Google Sheets; both go through the same duplicate detection, so a second run adds nothing.

CSV columns:

```
Date,Symbol,Action,Quantity,Price,Commission,Strategy,Account,Notes
2025-03-17,ABC,BUY,40,25.00,0,Example Strategy,Example Account,Initial purchase
```

- Validate first, then import. Without a sleeve, rows are routed by their Account and Strategy.
- A Google Sheet must be shared as "Anyone with the link can view" and have the same header row.
  `Date` may be `YYYY-MM-DD` or `YYYY/MM/DD`; `Action` is `Buy`/`Sell` in any case.
