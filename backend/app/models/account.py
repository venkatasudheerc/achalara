"""Account model - represents a sub-portfolio within a client"""
from sqlalchemy import Boolean, Column, String, ForeignKey
from sqlalchemy.orm import relationship
import uuid
from app.models.base import BaseModel


class Account(BaseModel):
    """Represents a client account (sub-portfolio)"""

    __tablename__ = "accounts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    account_number = Column(String(50), nullable=True)  # e.g., "10000001"
    name = Column(String(255), nullable=False)
    description = Column(String(500))
    # Which lots a sale closes first, as set at the brokerage: FIFO | MIN_TAX.
    cost_basis_method = Column(
        String(20), nullable=False, default="FIFO", server_default="FIFO"
    )
    # What kind of account it is, chosen when it is added (services/account_kind.py
    # lists them). Empty for an account made before kinds were chosen: its kind is
    # then read from its name.
    kind = Column(String(20))
    # The institution holding it, and the last four digits of the institution's
    # own number for it (not a feed's), as the owner sees them on statements.
    institution = Column(String(255))
    last_four = Column(String(4))
    # The owner keeps it to themselves: not even a spouse sees it (a minor's
    # guardians still do).
    is_private = Column(Boolean, nullable=False, default=False, server_default="false")

    # Relationships
    client = relationship("Client", back_populates="accounts")
    sleeves = relationship(
        "Sleeve", back_populates="account", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Account(id={self.id}, name={self.name}, client_id={self.client_id})>"
