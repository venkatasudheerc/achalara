"""Account model - represents a sub-portfolio within a client"""
from sqlalchemy import Column, String, ForeignKey
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

    # Relationships
    client = relationship("Client", back_populates="accounts")
    sleeves = relationship(
        "Sleeve", back_populates="account", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Account(id={self.id}, name={self.name}, client_id={self.client_id})>"
