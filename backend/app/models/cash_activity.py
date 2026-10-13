"""Cash activity model"""
from sqlalchemy import Column, Date, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
import uuid
from app.models.base import BaseModel

# Types that are investment income or cost and therefore part of returns.
# Everything else (contributions, withdrawals, transfers) moves cash in or out
# of the account without being a return, and is kept for audit only.
# Margin interest is a cost of the account, like a fee, kept under its own
# name so it can be shown for what it is.
MARGIN_INTEREST = "MARGIN_INTEREST"
INCOME_TYPES = ("DIVIDEND", "INTEREST", "FEE", MARGIN_INTEREST, "WITHHOLDING")


class CashActivity(BaseModel):
    """A non-trade money movement in a sleeve: dividends, fees, transfers.

    ``amount`` is signed from the holder's side: positive is cash received
    (dividend, interest), negative is cash paid (fee, tax withheld).
    """

    __tablename__ = "cash_activities"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sleeve_id = Column(
        String(36), ForeignKey("sleeves.id", ondelete="CASCADE"), nullable=False
    )
    activity_date = Column(Date, nullable=False)
    type = Column(String(20), nullable=False)
    symbol = Column(String(50))
    amount = Column(Numeric(18, 2), nullable=False)
    notes = Column(Text)
    external_id = Column(String(255), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint(
            "sleeve_id", "external_id", name="uq_cash_activity_sleeve_external"
        ),
    )

    sleeve = relationship("Sleeve", back_populates="cash_activities")

    def __repr__(self):
        return (
            f"<CashActivity(id={self.id}, type={self.type}, "
            f"symbol={self.symbol}, amount={self.amount})>"
        )
