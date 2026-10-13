"""add link started time to clients

Revision ID: 9c3f5a7d1e60
Revises: 7b1e4c9a2d35
Create Date: 2026-10-13 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9c3f5a7d1e60'
down_revision = '7b1e4c9a2d35'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'clients',
        sa.Column(
            'brokerage_link_started_at', sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column('clients', 'brokerage_link_started_at')
