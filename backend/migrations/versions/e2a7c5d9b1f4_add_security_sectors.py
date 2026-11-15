"""A copy of market data's sector for each symbol the app holds

The portal's sector view reads this copy, not market data, so it works when
market data cannot be reached. The daily job ``sector_copy`` fills it.

Revision ID: e2a7c5d9b1f4
Revises: d4f6a8c1e3b7
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "e2a7c5d9b1f4"
down_revision = "d4f6a8c1e3b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_sectors",
        sa.Column("symbol", sa.String(30), primary_key=True),
        sa.Column("kind", sa.String(20)),
        sa.Column("sector_code", sa.String(4)),
        sa.Column("sector_name", sa.String(40)),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("security_sectors")
