"""grant the read-only login (MD_READER_USER, md_reader by default) SELECT on md,
now and for later tables

The login itself is created by hand once per server (deploy/create-md-reader.sh),
so its password never enters the repository. Where it does not exist yet (tests,
a fresh database) this does nothing.

Revision ID: c6a9d4e2f8b1
Revises: b3e8f1a6d2c9
Create Date: 2026-11-08 23:00:00.000000

"""
import re

from alembic import op

from app.md.config import settings


# revision identifiers, used by Alembic.
revision = "c6a9d4e2f8b1"
down_revision = "b3e8f1a6d2c9"
branch_labels = None
depends_on = None


def _reader() -> str:
    name = settings.md_reader_user
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
        raise ValueError("MD_READER_USER: lower-case letters, digits and _ only")
    return name


def upgrade() -> None:
    reader = _reader()
    op.execute(
        f"""
        do $$
        begin
            if exists (select 1 from pg_roles where rolname = '{reader}') then
                grant usage on schema md to {reader};
                grant select on all tables in schema md to {reader};
                alter default privileges in schema md grant select on tables to {reader};
            end if;
        end $$
        """
    )


def downgrade() -> None:
    reader = _reader()
    op.execute(
        f"""
        do $$
        begin
            if exists (select 1 from pg_roles where rolname = '{reader}') then
                alter default privileges in schema md revoke select on tables from {reader};
                revoke select on all tables in schema md from {reader};
                revoke usage on schema md from {reader};
            end if;
        end $$
        """
    )
