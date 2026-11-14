"""Strategies fed by a link match sales to the oldest shares (FIFO).

Linking with Plaid created each account's strategy with the default round-trip
matching, meant for strategy sheets: it pairs a sale only with a buy of the same
quantity, so a sale of shares bought before the history is dropped and later
buys stay open. Every strategy a link feeds becomes FIFO, as the rules say. A
rebuild after this (the morning refresh, or /admin/rebuild-performance) brings
the openings and records up to date.

Revision ID: b8d3f1a6c2e4
Revises: a7c2e9f4b1d3
Create Date: 2026-11-14
"""
from alembic import op

revision = "b8d3f1a6c2e4"
down_revision = "a7c2e9f4b1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE sleeves SET accounting_method = 'FIFO'
        WHERE accounting_method <> 'FIFO'
          AND (account_id IN (SELECT account_id FROM brokerage_accounts
                              WHERE status = 'mapped' AND account_id IS NOT NULL)
               OR id IN (SELECT default_sleeve_id FROM brokerage_accounts
                         WHERE default_sleeve_id IS NOT NULL))
        """
    )


def downgrade() -> None:
    # Which strategies were round-trip before is not kept; FIFO stays.
    pass
