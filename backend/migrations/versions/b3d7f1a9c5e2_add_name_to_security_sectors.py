"""Add the security's name to the copy of market data's sectors

The Holdings view shows what each holding is called under its symbol. The
daily job ``sector_copy`` fills it from market data, like the sector.

Revision ID: b3d7f1a9c5e2
Revises: a9c4e1d7b3f2
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "b3d7f1a9c5e2"
down_revision = "a9c4e1d7b3f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("security_sectors", sa.Column("name", sa.String(200)))


def downgrade() -> None:
    op.drop_column("security_sectors", "name")
