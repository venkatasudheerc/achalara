"""label margin interest apart from fees

Revision ID: 877ed5cb4ec0
Revises: 4b4914658d28
Create Date: 2026-10-12 19:29:53.140780

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "877ed5cb4ec0"
down_revision = "4b4914658d28"
branch_labels = None
depends_on = None


# Margin interest was stored as a fee. The brokerage's own wording marks it:
# "INT 09/11-09/15 @12.000%05 DAY AVG BAL= ...". The type is part of the
# id a cash row is recognised by, so both move together.
_MARGIN_NOTE = "^INT [0-9]{2}/[0-9]{2}-[0-9]{2}/[0-9]{2} @"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE cash_activities
           SET type = 'MARGIN_INTEREST',
               external_id = replace(external_id, ':cash:FEE:', ':cash:MARGIN_INTEREST:')
         WHERE type = 'FEE' AND notes ~ '{_MARGIN_NOTE}'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE cash_activities
           SET type = 'FEE',
               external_id = replace(external_id, ':cash:MARGIN_INTEREST:', ':cash:FEE:')
         WHERE type = 'MARGIN_INTEREST'
        """
    )
