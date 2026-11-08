#!/bin/sh
# Create (or update the password of) the read-only database login research and
# the chatbot use. It may read the md schema and nothing else.
# Run once per server from deploy/, after MD_READER_PASSWORD is set in .env
# (MD_READER_USER is optional; it defaults to md_reader):
#   sudo sh create-md-reader.sh
# Then: sudo docker compose up -d backend (docker-compose.yml builds
# MD_READ_DATABASE_URL from the same name and password).
# The password is read from .env and never written anywhere else.
set -eu
cd "$(dirname "$0")"
setting() { grep "^$1=" .env | tail -n 1 | cut -d= -f2- || true; }
READER=$(setting MD_READER_USER); READER=${READER:-md_reader}
PASSWORD=$(setting MD_READER_PASSWORD)
OWNER=$(setting POSTGRES_USER); OWNER=${OWNER:-achalara}
DB=$(setting POSTGRES_DB); DB=${DB:-achalara}
if [ -z "$PASSWORD" ]; then
    echo "Set MD_READER_PASSWORD in deploy/.env first." >&2
    exit 1
fi
case "$READER" in
    "$OWNER" | *[!a-z0-9_]* | [0-9]*)
        echo "MD_READER_USER: lower-case letters, digits and _, not the owner's name." >&2
        exit 1 ;;
esac
docker compose exec -T db psql -q -v ON_ERROR_STOP=1 -U "$OWNER" -d "$DB" \
    -v reader="$READER" -v pw="$PASSWORD" -v db="$DB" <<'SQL'
SELECT format(
  CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'reader')
       THEN 'ALTER ROLE %I LOGIN PASSWORD %L'
       ELSE 'CREATE ROLE %I LOGIN PASSWORD %L' END, :'reader', :'pw') \gexec
ALTER ROLE :"reader" SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE :"db" TO :"reader";
GRANT USAGE ON SCHEMA md TO :"reader";
GRANT SELECT ON ALL TABLES IN SCHEMA md TO :"reader";
ALTER DEFAULT PRIVILEGES IN SCHEMA md GRANT SELECT ON TABLES TO :"reader";
REVOKE ALL ON SCHEMA public FROM :"reader";
SQL
echo "$READER is ready (read-only, md only). Now: sudo docker compose up -d backend"
