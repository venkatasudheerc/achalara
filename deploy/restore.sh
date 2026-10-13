#!/bin/sh
# Restore the database from a dump made by backup.sh (or by pg_dump -Fc).
# This REPLACES everything in the database. The backend is stopped meanwhile.
#
#   ./restore.sh /srv/achalara-backups/achalara-2026-01-31.dump
set -eu

DUMP="${1:?give the path of the dump to restore}"
test -s "$DUMP" || { echo "No such dump: $DUMP" >&2; exit 1; }
cd "$(dirname "$0")"

printf 'This replaces the whole database with %s. Type "restore" to go on: ' "$DUMP"
read -r answer
[ "$answer" = "restore" ] || { echo "Stopped; nothing changed."; exit 1; }

docker compose stop backend
docker compose exec -T db sh -c 'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$DUMP"
docker compose start backend
echo "Restored. Check the site, then sign in."
