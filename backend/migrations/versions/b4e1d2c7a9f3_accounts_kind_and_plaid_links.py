"""Accounts carry a chosen kind, institution and real last four; Plaid links

Revision ID: b4e1d2c7a9f3
Revises: 6dc4fe951a70
Create Date: 2026-11-13
"""
from alembic import op
import sqlalchemy as sa

revision = "b4e1d2c7a9f3"
down_revision = "6dc4fe951a70"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("kind", sa.String(20), nullable=True))
    op.add_column("accounts", sa.Column("institution", sa.String(255), nullable=True))
    op.add_column("accounts", sa.Column("last_four", sa.String(4), nullable=True))
    op.add_column(
        "brokerage_connections", sa.Column("access_token_enc", sa.Text(), nullable=True)
    )
    op.add_column(
        "brokerage_connections", sa.Column("products", sa.String(255), nullable=True)
    )
    op.add_column(
        "brokerage_connections",
        sa.Column("consent_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "brokerage_connections", sa.Column("transactions_cursor", sa.Text(), nullable=True)
    )
    op.add_column(
        "brokerage_accounts",
        sa.Column("persistent_account_id", sa.String(255), nullable=True),
    )
    op.add_column("brokerage_accounts", sa.Column("mask", sa.String(4), nullable=True))
    op.add_column(
        "brokerage_accounts", sa.Column("plaid_type", sa.String(30), nullable=True)
    )
    op.add_column(
        "brokerage_accounts", sa.Column("plaid_subtype", sa.String(50), nullable=True)
    )


def downgrade():
    for column in ("plaid_subtype", "plaid_type", "mask", "persistent_account_id"):
        op.drop_column("brokerage_accounts", column)
    for column in ("transactions_cursor", "consent_expires_at", "products", "access_token_enc"):
        op.drop_column("brokerage_connections", column)
    for column in ("last_four", "institution", "kind"):
        op.drop_column("accounts", column)
