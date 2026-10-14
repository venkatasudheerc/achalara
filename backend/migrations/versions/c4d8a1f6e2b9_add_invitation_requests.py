"""add invitation requests

Revision ID: c4d8a1f6e2b9
Revises: 9c3f5a7d1e60
Create Date: 2026-10-13 23:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4d8a1f6e2b9'
down_revision = '9c3f5a7d1e60'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'invitation_requests',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=40), nullable=False),
        sa.Column('note', sa.String(length=1000), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_invitation_requests_email'),
        'invitation_requests',
        ['email'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_invitation_requests_email'), table_name='invitation_requests'
    )
    op.drop_table('invitation_requests')
