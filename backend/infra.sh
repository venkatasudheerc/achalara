#!/usr/bin/env bash
#
# infra.sh — manage the PMS local stack (Colima → Postgres/Redis → Alembic → app)
# See INFRA.md for the full runbook. Run from anywhere; paths resolve to backend/.
#
# Usage:
#   ./infra.sh up        Start everything: Colima, containers, migrations, app (foreground)
#   ./infra.sh up -d     Same, but run the app in the background (logs to /tmp/pms_uvicorn.log)
#   ./infra.sh down      Stop app + containers (DB data kept) and stop the Colima VM
#   ./infra.sh restart   down then up -d
#   ./infra.sh status    Show state of all 4 layers
#   ./infra.sh logs      Tail container logs (Ctrl+C to exit)
#   ./infra.sh applog    Tail the backgrounded app log
#   ./infra.sh db        Open a psql shell into the Postgres container
#   ./infra.sh migrate   Apply Alembic migrations (alembic upgrade head)
#   ./infra.sh clean     DESTROY the database volume and recreate empty (prompts first)
#
set -euo pipefail

# Resolve to the backend/ directory (where this script and docker-compose.yml live)
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BACKEND_DIR"

PORT="${PORT:-8000}"
APP_LOG="/tmp/pms_uvicorn.log"

# --- colors (no-op if not a tty) ---------------------------------------------
if [ -t 1 ]; then G='\033[32m'; Y='\033[33m'; R='\033[31m'; B='\033[1m'; X='\033[0m'; else G=; Y=; R=; B=; X=; fi
ok()   { printf "${G}✓${X} %s\n" "$1"; }
warn() { printf "${Y}…${X} %s\n" "$1"; }
err()  { printf "${R}✗${X} %s\n" "$1"; }
hdr()  { printf "\n${B}%s${X}\n" "$1"; }

activate_venv() {
  if [ -f venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
  else
    err "venv not found at backend/venv — run: python3 -m venv venv && pip install -r requirements.txt"
    exit 1
  fi
}

# --- layer helpers -----------------------------------------------------------
colima_up() {
  if colima status >/dev/null 2>&1; then ok "Colima already running"
  else warn "starting Colima VM…"; colima start >/dev/null 2>&1 && ok "Colima started"; fi
}

containers_up() {
  warn "starting containers (Postgres + Redis)…"
  docker-compose up -d >/dev/null 2>&1
  # wait for postgres health
  for _ in $(seq 1 30); do
    if [ "$(docker inspect --format '{{.State.Health.Status}}' pms-db 2>/dev/null)" = "healthy" ]; then
      ok "Postgres healthy"; break
    fi
    sleep 2
  done
  [ "$(docker inspect --format '{{.State.Health.Status}}' pms-cache 2>/dev/null)" = "healthy" ] && ok "Redis healthy"
}

migrate() {
  activate_venv
  warn "applying migrations (alembic upgrade head)…"
  alembic -n md upgrade head >/dev/null 2>&1 && ok "md schema at head"
  alembic upgrade head >/dev/null 2>&1 && ok "schema at head ($(alembic current 2>/dev/null | awk '{print $1}'))"
}

app_fg() {
  activate_venv
  hdr "Starting app on :$PORT (foreground — Ctrl+C to stop)"
  exec uvicorn app.main:app --reload --port "$PORT"
}

app_bg() {
  activate_venv
  if pgrep -f "uvicorn app.main:app" >/dev/null 2>&1; then
    warn "app already running (pid $(pgrep -f 'uvicorn app.main:app' | head -1))"
    return
  fi
  nohup uvicorn app.main:app --port "$PORT" > "$APP_LOG" 2>&1 &
  for _ in $(seq 1 20); do
    if curl -s "http://localhost:$PORT/health" >/dev/null 2>&1; then
      ok "app up on http://localhost:$PORT  (docs: /docs, log: $APP_LOG)"; return
    fi
    sleep 1
  done
  err "app did not become healthy — check $APP_LOG"; tail -20 "$APP_LOG" || true
}

# --- commands ----------------------------------------------------------------
cmd_up() {
  hdr "Bringing stack up (1→4)"
  colima_up
  containers_up
  migrate
  if [ "${1:-}" = "-d" ]; then app_bg; else app_fg; fi
}

cmd_down() {
  hdr "Bringing stack down (4→1)"
  if pgrep -f "uvicorn app.main:app" >/dev/null 2>&1; then
    pkill -f "uvicorn app.main:app" && ok "app stopped"
  else warn "app not running"; fi
  docker-compose down >/dev/null 2>&1 && ok "containers removed (DB volume kept)"
  if colima status >/dev/null 2>&1; then colima stop >/dev/null 2>&1 && ok "Colima stopped"; fi
}

cmd_status() {
  hdr "Stack status"
  if colima status >/dev/null 2>&1; then ok "Colima: running"; else err "Colima: stopped"; fi

  if docker info >/dev/null 2>&1; then
    docker-compose ps --format "  {{.Name}}: {{.Status}}" 2>/dev/null | grep -v '^time=' || warn "no containers"
  else
    err "Docker daemon unreachable (Colima down)"
  fi

  if docker info >/dev/null 2>&1 && [ "$(docker inspect --format '{{.State.Health.Status}}' pms-db 2>/dev/null)" = "healthy" ]; then
    activate_venv
    printf "  schema revision: %s\n" "$(alembic current 2>/dev/null | awk '{print $1}' || echo '?')"
  fi

  if curl -s "http://localhost:$PORT/health" >/dev/null 2>&1; then
    ok "app: healthy on :$PORT"
  else err "app: not responding on :$PORT"; fi
}

cmd_clean() {
  printf "${R}This DESTROYS all database data (drops the postgres volume).${X} Continue? [y/N] "
  read -r ans
  [ "$ans" = "y" ] || { echo "aborted"; exit 0; }
  colima_up
  docker-compose down -v >/dev/null 2>&1 && ok "volume dropped"
  containers_up
  migrate
  ok "fresh database ready"
}

usage() {
  cat <<'EOF'
infra.sh — manage the PMS local stack (Colima → Postgres/Redis → Alembic → app)
See INFRA.md for the full runbook.

Usage: ./infra.sh <command>
  up         Start everything: Colima, containers, migrations, app (foreground)
  up -d      Same, but run the app in the background (log: /tmp/pms_uvicorn.log)
  down       Stop app + containers (DB data kept) and stop the Colima VM
  restart    down, then up -d
  status     Show state of all 4 layers
  logs       Tail container logs (Ctrl+C to exit)
  applog     Tail the backgrounded app log
  db         Open a psql shell into the Postgres container
  migrate    Apply Alembic migrations (alembic upgrade head)
  clean      DESTROY the database volume and recreate empty (prompts first)
EOF
}

case "${1:-}" in
  up)      shift; cmd_up "${1:-}";;
  down)    cmd_down;;
  restart) cmd_down; cmd_up -d;;
  status)  cmd_status;;
  logs)    docker-compose logs -f;;
  applog)  tail -f "$APP_LOG";;
  db)      docker exec -it pms-db psql -U postgres -d pms_dev;;
  migrate) migrate;;
  clean)   cmd_clean;;
  help|-h|--help) usage;;
  *)       usage; exit 1;;
esac
