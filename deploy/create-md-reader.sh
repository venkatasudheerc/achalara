#!/bin/sh
# Create (or update the password of) md_reader: the read-only database login
# research and the chatbot use. It may read the md schema and nothing else.
# Run once per server from deploy/, after MD_READER_PASSWORD is set in .env:
#   sudo sh create-md-reader.sh
# Then run: sudo docker compose up -d backend (docker-compose.yml builds
# MD_READ_DATABASE_URL from the same password).
# The password is read from .env and never written anywhere else.
set -eu
cd "$(dirname "$0")"
PASSWORD=$(grep '^MD_READER_PASSWORD=' .env | cut -d= -f2-)
if [ -z "$PASSWORD" ]; then
    echo "Set MD_READER_PASSWORD in deploy/.env first." >&2
    exit 1
fi
docker compose exec -T -e MD_READER_PASSWORD="$PASSWORD" db sh -c '
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v pw="$MD_READER_PASSWORD" <<SQL
SELECT format(
  CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '"'"'md_reader'"'"')
       THEN '"'"'ALTER ROLE md_reader LOGIN PASSWORD %L'"'"'
       ELSE '"'"'CREATE ROLE md_reader LOGIN PASSWORD %L'"'"' END, :'"'"'pw'"'"') \gexec
ALTER ROLE md_reader SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO md_reader;
GRANT USAGE ON SCHEMA md TO md_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA md TO md_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA md GRANT SELECT ON TABLES TO md_reader;
REVOKE ALL ON SCHEMA public FROM md_reader;
SQL
'
echo "md_reader is ready. Set MD_READ_DATABASE_URL in .env, then: sudo docker compose up -d"
