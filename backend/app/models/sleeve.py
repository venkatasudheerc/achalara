"""Sleeve model - a strategy as run within a specific account"""
from sqlalchemy import Column, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
import uuid
from app.models.base import BaseModel


class Sleeve(BaseModel):
    """A strategy definition applied within a single account.

    The account x strategy instance that owns trades and positions. One global
    Strategy can have many sleeves (the same strategy run across many accounts).
    """

    __tablename__ = "sleeves"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    strategy_id = Column(
        String(36), ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=False
    )

    # How SELLs are matched to BUYs when deriving positions. ROUND_TRIP pairs
    # equal quantities (strategy sheets record discrete round trips); FIFO
    # consumes the oldest lots, which is what real brokerage activity needs.
    accounting_method = Column(
        String(20), nullable=False, default="ROUND_TRIP", server_default="ROUND_TRIP"
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id", "strategy_id", name="uq_sleeve_account_strategy"
        ),
    )

    account = relationship("Account", back_populates="sleeves")
    strategy = relationship("Strategy", back_populates="sleeves")
    trades = relationship(
        "Trade", back_populates="sleeve", cascade="all, delete-orphan"
    )
    positions = relationship(
        "Position", back_populates="sleeve", cascade="all, delete-orphan"
    )
    cash_activities = relationship(
        "CashActivity", back_populates="sleeve", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<Sleeve(id={self.id}, account_id={self.account_id}, "
            f"strategy_id={self.strategy_id})>"
        )
