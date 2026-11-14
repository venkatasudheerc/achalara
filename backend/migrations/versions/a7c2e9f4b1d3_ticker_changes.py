"""Ticker changes as corporate actions.

A company that changes its ticker leaves trades under the old symbol and
holdings under the new one, so an account's shares cannot be worked back.
``perf.corporate_action`` gains ``new_symbol`` and records a change as a
``RENAME`` (ratio 1); ``corporate_actions.adjusted_trades`` reads old trades
under the new symbol. Stored trades are never changed. Changes are entered with
``python -m app.cli add-ticker-change``.

Revision ID: a7c2e9f4b1d3
Revises: e3a9c1f7b5d2
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op

revision = "a7c2e9f4b1d3"
down_revision = "e3a9c1f7b5d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "corporate_action",
        sa.Column("new_symbol", sa.String(length=50), nullable=True),
        schema="perf",
    )


def downgrade() -> None:
    op.execute("DELETE FROM perf.corporate_action WHERE action_type = 'RENAME'")
    op.drop_column("corporate_action", "new_symbol", schema="perf")
