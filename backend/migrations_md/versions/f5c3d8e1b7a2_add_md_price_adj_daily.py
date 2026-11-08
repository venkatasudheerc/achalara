"""add md adjusted daily closes (total return)

Revision ID: f5c3d8e1b7a2
Revises: e4b2c7d9a1f3
Create Date: 2026-11-08 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f5c3d8e1b7a2"
down_revision = "e4b2c7d9a1f3"
branch_labels = None
depends_on = None

S = "md"


def upgrade() -> None:
    op.create_table(
        "price_adj_daily",
        sa.Column(
            "security_id",
            sa.String(36),
            sa.ForeignKey("md.security.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("price_date", sa.Date(), primary_key=True),
        sa.Column("adj_close", sa.Numeric(18, 6), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema=S,
    )
    op.create_index(
        "ix_md_price_adj_daily_price_date", "price_adj_daily", ["price_date"], schema=S
    )


def downgrade() -> None:
    op.drop_index("ix_md_price_adj_daily_price_date", "price_adj_daily", schema=S)
    op.drop_table("price_adj_daily", schema=S)
