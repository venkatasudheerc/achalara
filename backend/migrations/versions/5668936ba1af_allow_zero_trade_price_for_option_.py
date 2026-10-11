"""allow zero trade price for option expiry and assignment

Revision ID: 5668936ba1af
Revises: b27ebdc1d5d0
Create Date: 2026-10-10 21:56:24.679534

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5668936ba1af'
down_revision = 'b27ebdc1d5d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # An option that expires or is assigned leaves the account at no price,
    # and is recorded as a closing trade at zero.
    op.drop_constraint("positive_price", "trades", type_="check")
    op.create_check_constraint("non_negative_price", "trades", "price >= 0")


def downgrade() -> None:
    # Fails if any zero-priced trade exists; remove those first.
    op.drop_constraint("non_negative_price", "trades", type_="check")
    op.create_check_constraint("positive_price", "trades", "price > 0")
