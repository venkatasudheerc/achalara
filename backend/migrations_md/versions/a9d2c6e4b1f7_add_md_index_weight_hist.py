"""add md index weights (percent of the index fund, by day)

Revision ID: a9d2c6e4b1f7
Revises: c6a9d4e2f8b1
Create Date: 2026-11-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a9d2c6e4b1f7"
down_revision = "c6a9d4e2f8b1"
branch_labels = None
depends_on = None

S = "md"


def upgrade() -> None:
    op.create_table(
        "index_weight_hist",
        sa.Column(
            "index_code",
            sa.String(12),
            sa.ForeignKey("md.index_def.code"),
            primary_key=True,
        ),
        sa.Column(
            "security_id",
            sa.String(36),
            sa.ForeignKey("md.security.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("as_of", sa.Date(), primary_key=True),
        sa.Column("weight", sa.Numeric(10, 6), nullable=False),
        sa.Column("source_file_id", sa.String(36), sa.ForeignKey("md.source_file.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema=S,
    )


def downgrade() -> None:
    op.drop_table("index_weight_hist", schema=S)
