"""confirm invitation requests by email

Revision ID: e7a2c9d41b53
Revises: c4d8a1f6e2b9
Create Date: 2026-10-14 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7a2c9d41b53'
down_revision = 'c4d8a1f6e2b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'invitation_requests',
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'invitation_requests',
        sa.Column('confirm_token_hash', sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f('ix_invitation_requests_confirm_token_hash'),
        'invitation_requests',
        ['confirm_token_hash'],
        unique=False,
    )
    # Requests kept before confirmation existed stay on the list.
    op.execute(
        "UPDATE invitation_requests SET confirmed_at = created_at "
        "WHERE confirmed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_invitation_requests_confirm_token_hash'),
        table_name='invitation_requests',
    )
    op.drop_column('invitation_requests', 'confirm_token_hash')
    op.drop_column('invitation_requests', 'confirmed_at')
