"""A copy of the S&P 500's record for this week and month

The Dashboard's market-pattern tile reads this copy, not market data, so it
works when market data cannot be reached. The daily job ``market_pattern_copy``
fills it.

Revision ID: a9c4e1d7b3f2
Revises: f3b8d6e0a2c5
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "a9c4e1d7b3f2"
down_revision = "f3b8d6e0a2c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_pattern_copies",
        sa.Column("key", sa.String(30), primary_key=True),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("market_pattern_copies")
