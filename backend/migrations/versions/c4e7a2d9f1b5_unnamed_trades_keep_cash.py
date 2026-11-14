"""A feed's trade it could not name keeps its cash.

Plaid sends many of Vanguard's option trades with no symbol. They were set aside
with no cash, so the account's cash worked back short by their premiums and the
account opened empty. The cash of each such buy or sale already stored is
restored from its own row (Plaid: a positive amount is money out). A rebuild
after this brings the openings up to date.

Revision ID: c4e7a2d9f1b5
Revises: b8d3f1a6c2e4
Create Date: 2026-11-14
"""
from alembic import op

revision = "c4e7a2d9f1b5"
down_revision = "b8d3f1a6c2e4"
branch_labels = None
depends_on = None


UNNAMED = """
    b.outcome = 'skipped:unreadable'
    AND (b.type LIKE 'PLAID BUY/%' OR b.type LIKE 'PLAID SELL/%')
    AND COALESCE(b.cash_amount, 0) = 0
    AND b.payload->>'amount' IS NOT NULL
"""


def upgrade() -> None:
    # Already named by an uploaded file (its trade carries the same cash within
    # three days): leave the cash with the file's row, marked as such.
    op.execute(
        f"""
        UPDATE brokerage_activities b SET outcome = 'skipped:unreadable, on file'
        WHERE {UNNAMED}
          AND EXISTS (
            SELECT 1 FROM brokerage_activities v
            WHERE v.brokerage_account_id = b.brokerage_account_id
              AND v.source_activity_id LIKE 'vanguard:%'
              AND v.outcome = 'trade'
              AND ABS(v.cash_amount + CAST(b.payload->>'amount' AS NUMERIC)) <= 0.01
              AND ABS(v.activity_date - b.activity_date) <= 3
          )
        """
    )
    op.execute(
        f"""
        UPDATE brokerage_activities b
        SET cash_amount = -CAST(b.payload->>'amount' AS NUMERIC)
        WHERE {UNNAMED}
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE brokerage_activities SET cash_amount = 0, outcome = 'skipped:unreadable'
        WHERE outcome IN ('skipped:unreadable', 'skipped:unreadable, on file')
          AND (type LIKE 'PLAID BUY/%' OR type LIKE 'PLAID SELL/%')
        """
    )
