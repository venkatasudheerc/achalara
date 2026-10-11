"""Trade model"""
from sqlalchemy import (
    Column,
    String,
    Text,
    Numeric,
    Date,
    ForeignKey,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
import uuid
from app.models.base import BaseModel


class Trade(BaseModel):
    """Individual trade transaction"""

    __tablename__ = "trades"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sleeve_id = Column(
        String(36), ForeignKey("sleeves.id", ondelete="CASCADE"), nullable=False
    )
    trade_date = Column(Date, nullable=False)
    # Wide enough for exchange-prefixed tickers ("NYSEARCA:VOO") and the
    # longer identifiers aggregators can return.
    symbol = Column(String(50), nullable=False)
    action = Column(String(10), nullable=False)  # BUY or SELL
    # 8 decimal places: brokerages report fractional shares from dividend
    # reinvestment well below the 6 places this previously allowed, and
    # silently truncating them corrupts cost basis.
    quantity = Column(Numeric(18, 8), nullable=False)
    price = Column(Numeric(15, 6), nullable=False)
    commission = Column(Numeric(15, 6), default=0)
    # Text, not String(500): broker-supplied descriptions are unbounded.
    notes = Column(Text)
    google_sheet_row_id = Column(String(255), unique=True)
    # Source-derived idempotency key (see connectors/models.NormalizedTrade).
    # Nullable because trades predating it — and any created directly via the
    # API rather than ingestion — have none. Uniqueness is scoped per sleeve so
    # the same trade legitimately appearing in two sleeves is not blocked.
    external_id = Column(String(255), nullable=True, index=True)
    # What kind of security this is (ETF, STOCK, ADR, ...), as the source
    # reported it. NULL for sources that do not say (CSV, Sheets, manual).
    security_type = Column(String(20), nullable=True)

    __table_args__ = (
        CheckConstraint("action IN ('BUY', 'SELL')", name="valid_action"),
        CheckConstraint("quantity > 0", name="positive_quantity"),
        # Zero is a real price: an option that expires or is assigned leaves
        # the account for nothing.
        CheckConstraint("price >= 0", name="non_negative_price"),
        UniqueConstraint("sleeve_id", "external_id", name="uq_trade_sleeve_external"),
    )

    sleeve = relationship("Sleeve", back_populates="trades")

    def __repr__(self):
        return f"<Trade(id={self.id}, symbol={self.symbol}, action={self.action}, qty={self.quantity})>"
