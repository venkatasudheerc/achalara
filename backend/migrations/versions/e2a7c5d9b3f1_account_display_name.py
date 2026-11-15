"""An account's own name, given by its owner.

The custodian's name ("Individual Brokerage Account") stays in ``name``; the
owner may call it something of their own ("Pat's trading account"), shown in its
place, with the custodian's name beneath. Empty means none given.

Revision ID: e2a7c5d9b3f1
Revises: c4e7a2d9f1b5
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op

revision = "e2a7c5d9b3f1"
down_revision = "c4e7a2d9f1b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("display_name", sa.String(60), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "display_name")
