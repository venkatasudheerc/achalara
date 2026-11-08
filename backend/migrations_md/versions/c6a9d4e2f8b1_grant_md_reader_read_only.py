"""grant the read-only role md_reader SELECT on md, now and for later tables

The role itself is created by hand once per server (deploy/create-md-reader.sh),
so its password never enters the repository. Where it does not exist yet (tests,
a fresh database) this does nothing.

Revision ID: c6a9d4e2f8b1
Revises: b3e8f1a6d2c9
Create Date: 2026-11-08 23:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "c6a9d4e2f8b1"
down_revision = "b3e8f1a6d2c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        do $$
        begin
            if exists (select 1 from pg_roles where rolname = 'md_reader') then
                grant usage on schema md to md_reader;
                grant select on all tables in schema md to md_reader;
                alter default privileges in schema md grant select on tables to md_reader;
            end if;
        end $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        do $$
        begin
            if exists (select 1 from pg_roles where rolname = 'md_reader') then
                alter default privileges in schema md revoke select on tables from md_reader;
                revoke select on all tables in schema md from md_reader;
                revoke usage on schema md from md_reader;
            end if;
        end $$
        """
    )
