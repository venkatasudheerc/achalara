"""add cost basis method to accounts

Revision ID: 4b4914658d28
Revises: afd1f078479c
Create Date: 2026-10-12 09:00:20.054531

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4b4914658d28'
down_revision = 'afd1f078479c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'accounts',
        sa.Column('cost_basis_method', sa.String(length=20), server_default='FIFO', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('accounts', 'cost_basis_method')
