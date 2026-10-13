"""add account fingerprint to brokerage accounts

Revision ID: 7b1e4c9a2d35
Revises: 320d958bd1a5
Create Date: 2026-10-13 19:40:00.000000

"""
import hashlib
import re

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7b1e4c9a2d35'
down_revision = '320d958bd1a5'
branch_labels = None
depends_on = None


def _fingerprint(institution, name):
    """As ``connection_service.account_fingerprint``, from what is on file."""
    runs = re.findall(r"\d{6,}", name or "")
    if not runs:
        return None
    key = f"{(institution or '').strip().lower()}|{max(runs, key=len)}"
    return hashlib.sha256(key.encode()).hexdigest()


def upgrade() -> None:
    op.add_column(
        'brokerage_accounts',
        sa.Column('account_fingerprint', sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f('ix_brokerage_accounts_account_fingerprint'),
        'brokerage_accounts',
        ['account_fingerprint'],
        unique=False,
    )

    # Accounts already on file get theirs now, so the check covers them before
    # the next time the source is asked.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT a.id, a.name, c.institution FROM brokerage_accounts a "
            "JOIN brokerage_connections c ON c.id = a.connection_id"
        )
    ).fetchall()
    for row_id, name, institution in rows:
        value = _fingerprint(institution, name)
        if value:
            bind.execute(
                sa.text(
                    "UPDATE brokerage_accounts SET account_fingerprint = :value "
                    "WHERE id = :id"
                ),
                {"value": value, "id": row_id},
            )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_brokerage_accounts_account_fingerprint'),
        table_name='brokerage_accounts',
    )
    op.drop_column('brokerage_accounts', 'account_fingerprint')
