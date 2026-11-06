# Infrastructure Runbook — PMS Backend

How to start, stop, check, and restart the local stack. Run everything from `backend/`:

```bash
cd "/Users/sai/Documents/Github 2/Achalara/backend"
```

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
| 3. Schema | Alembic migrations → all 7 tables | `alembic` |
| 4. App | FastAPI via uvicorn (port 8000) | `uvicorn` |

> Order matters: bring layers **up 1→4** and take them **down 4→1**. The app needs the DB; the DB needs the containers; the containers need Colima.

---

## Full stack — cold start

```bash
cd "/Users/sai/Documents/Github 2/Achalara/backend"
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

The scheduler (APScheduler daily sync) starts/stops automatically with the app when
`SCHEDULER_ENABLED=true` (the default). Startup log shows
`APScheduler started — daily sync job scheduled at 16:00 UTC`. To run the app without it,
set `SCHEDULER_ENABLED=false` in `.env`.

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
| Want a clean database | `docker-compose down -v && docker-compose up -d && alembic upgrade head` |
| Tests don't need Docker | `pytest` uses in-memory SQLite — runs without any of the above |
