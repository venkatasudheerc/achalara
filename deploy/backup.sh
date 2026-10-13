#!/bin/sh
# Nightly database backup. Writes one compressed dump per day and keeps the
# last KEEP_DAYS. Run by cron (see setup-server.sh); safe to run by hand.
set -eu

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/srv/achalara-backups}"
# The app's status page reads the result from here; it holds no data.
STATUS_DIR="${STATUS_DIR:-/srv/achalara-status}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date -u +%Y-%m-%d)"
TARGET="$BACKUP_DIR/achalara-$STAMP.dump"

mkdir -p "$BACKUP_DIR"
cd "$DEPLOY_DIR"

# Written under a temporary name first, so a failed run never looks like a backup.
docker compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$TARGET.part"
test -s "$TARGET.part"
mv "$TARGET.part" "$TARGET"
chmod 600 "$TARGET"

find "$BACKUP_DIR" -name 'achalara-*.dump' -mtime "+$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name '*.part' -mtime +1 -delete

echo "$(date -u +%FT%TZ) backup ok: $TARGET ($(du -h "$TARGET" | cut -f1))" >> "$BACKUP_DIR/backup.log"

mkdir -p "$STATUS_DIR"
printf '{"at": "%s", "file": "%s", "size_bytes": %s}\n' \
    "$(date -u +%FT%TZ)" "$(basename "$TARGET")" "$(wc -c < "$TARGET" | tr -d ' ')" \
    > "$STATUS_DIR/backup.json"
chmod 644 "$STATUS_DIR/backup.json"
