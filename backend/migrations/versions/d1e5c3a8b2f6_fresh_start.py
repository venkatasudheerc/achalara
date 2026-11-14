"""A fresh start: no client data is carried over from before Plaid

Achalara starts again with Plaid and the custodian's own files as its only sources
(2026-11-14). This removes every client, client login, account and everything
recorded for them: transactions, cash, positions, the daily record and holdings,
groups, sharing, feed links and their source rows, and sync logs. Clients and
their accounts are then added afresh, through Plaid and uploads.

Kept: advisor logins (detached from any client first, so they survive), the
firm-wide strategy definitions, prices and recorded splits (facts about
securities, not clients), market data and index history, and invitation requests.

There is no downgrade: what is removed comes back only from a backup.

Revision ID: d1e5c3a8b2f6
Revises: b4e1d2c7a9f3
Create Date: 2026-11-14
"""
from alembic import op

revision = "d1e5c3a8b2f6"
down_revision = "b4e1d2c7a9f3"
branch_labels = None
depends_on = None

# Children first, so the order holds whatever each foreign key does on delete.
CLEARED = (
    "perf.daily_holding",
    "perf.daily_valuation",
    "brokerage_activities",
    "brokerage_accounts",
    "brokerage_connections",
    "trades",
    "cash_activities",
    "positions",
    "sheet_sync_configs",
    "account_group_members",
    "account_groups",
    "account_access",
    "sleeves",
    "accounts",
    "sync_logs",
)


def upgrade():
    for table in CLEARED:
        op.execute(f"DELETE FROM {table}")
    # An advisor who was also on file as a client keeps their login.
    op.execute("UPDATE users SET client_id = NULL WHERE role = 'advisor'")
    op.execute(
        "DELETE FROM user_sessions WHERE user_id IN (SELECT id FROM users WHERE role = 'client')"
    )
    op.execute(
        "DELETE FROM auth_tokens WHERE user_id IN (SELECT id FROM users WHERE role = 'client')"
    )
    op.execute("DELETE FROM users WHERE role = 'client'")
    op.execute("DELETE FROM clients")


def downgrade():
    # Nothing to undo in the schema; the data comes back only from a backup.
    pass
