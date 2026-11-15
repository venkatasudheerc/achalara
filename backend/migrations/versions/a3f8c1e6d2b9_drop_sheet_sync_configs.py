"""Google Sheets is no longer a source: drop the sheet sync configurations.

The Imports page and the daily sheet sync are retired, and nothing else reads or
writes ``sheet_sync_configs``. Trades keep ``google_sheet_row_id`` (what they
were), and ``sync_logs`` stays: the shared ingestion still writes it.

Downgrade puts the empty table back as it was, with its cascade to sleeves.

Revision ID: a3f8c1e6d2b9
Revises: e2a7c5d9b3f1
Create Date: 2026-11-14
"""
from alembic import op
import sqlalchemy as sa

revision = "a3f8c1e6d2b9"
down_revision = "e2a7c5d9b3f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sheet_sync_configs")


def downgrade() -> None:
    op.create_table(
        "sheet_sync_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sleeve_id", sa.String(length=36), nullable=False),
        sa.Column("sheet_id", sa.String(length=255), nullable=False),
        sa.Column("range_name", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["sleeve_id"],
            ["sleeves.id"],
            name="sheet_sync_configs_sleeve_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
