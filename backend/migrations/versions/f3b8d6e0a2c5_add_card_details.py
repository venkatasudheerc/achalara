"""A credit card's limits and what is due, as its institution reports them

One row per card account, replaced by the daily Plaid refresh and shown on the
Accounts view. No account number, no credentials.

Revision ID: f3b8d6e0a2c5
Revises: e2a7c5d9b1f4
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "f3b8d6e0a2c5"
down_revision = "e2a7c5d9b1f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_details",
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("credit_limit", sa.Numeric(18, 2)),
        sa.Column("available_credit", sa.Numeric(18, 2)),
        sa.Column("cash_advance_limit", sa.Numeric(18, 2)),
        sa.Column("minimum_payment", sa.Numeric(18, 2)),
        sa.Column("next_payment_due_date", sa.Date()),
        sa.Column("last_payment_amount", sa.Numeric(18, 2)),
        sa.Column("last_payment_date", sa.Date()),
        sa.Column("last_statement_balance", sa.Numeric(18, 2)),
        sa.Column("is_overdue", sa.Boolean()),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("card_details")
