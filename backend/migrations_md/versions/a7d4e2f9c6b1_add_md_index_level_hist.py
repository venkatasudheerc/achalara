"""add md index levels, and link each index to its level

Revision ID: a7d4e2f9c6b1
Revises: f5c3d8e1b7a2
Create Date: 2026-11-08 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7d4e2f9c6b1"
down_revision = "f5c3d8e1b7a2"
branch_labels = None
depends_on = None

S = "md"
LEVELS = {"R1000": "RUI", "R2000": "RUT", "R3000": "RUA", "SP500": "SPX"}


def upgrade() -> None:
    op.create_table(
        "index_level_hist",
        sa.Column("symbol", sa.String(12), primary_key=True),
        sa.Column("price_date", sa.Date(), primary_key=True),
        sa.Column("close", sa.Numeric(18, 4), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema=S,
    )
    for code, level in LEVELS.items():
        op.execute(
            sa.text(
                "update md.index_def set level_symbol = :l where code = :c"
            ).bindparams(l=level, c=code)
        )


def downgrade() -> None:
    op.execute(
        "update md.index_def set level_symbol = null where code in ('R1000', 'R2000', 'R3000')"
    )
    op.drop_table("index_level_hist", schema=S)
