"""Position model"""
from sqlalchemy import (
    Column,
    String,
    Numeric,
    DateTime,
    ForeignKey,
    func,
)
from sqlalchemy.orm import relationship
import uuid
from app.models.base import BaseModel


class Position(BaseModel):
    """Open or closed position in a security for a sleeve.

    status='OPEN'   — currently held; quantity > 0
    status='CLOSED' — fully exited; quantity = 0, realized_gain is set
    """

    __tablename__ = "positions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sleeve_id = Column(
        String(36), ForeignKey("sleeves.id", ondelete="CASCADE"), nullable=False
    )
    # Widths track trades.symbol / trades.quantity, since positions are
    # derived from trades and must not truncate what a trade can hold.
    symbol = Column(String(50), nullable=False)
    status = Column(String(10), nullable=False, default="OPEN")  # OPEN | CLOSED
    quantity = Column(Numeric(18, 8), nullable=False)
    cost_basis = Column(Numeric(18, 2), nullable=False)
    current_price = Column(Numeric(15, 6))
    market_value = Column(Numeric(18, 2))
    unrealized_gain = Column(Numeric(18, 2))
    realized_gain = Column(Numeric(18, 2))
    realized_gain_pct = Column(Numeric(10, 4))
    closed_at = Column(DateTime(timezone=True))
    last_updated = Column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now()
    )

    # UniqueConstraint removed: a symbol can have one OPEN + many CLOSED rows
    __table_args__ = ()

    sleeve = relationship("Sleeve", back_populates="positions")

    def __repr__(self):
        return f"<Position(id={self.id}, symbol={self.symbol}, qty={self.quantity}, status={self.status})>"
