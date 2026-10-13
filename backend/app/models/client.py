"""Client model"""
from sqlalchemy import Column, DateTime, String
from sqlalchemy.orm import relationship
import uuid
from app.models.base import BaseModel


class Client(BaseModel):
    """Client account"""

    __tablename__ = "clients"

    # Use string for UUID to work with both PostgreSQL and SQLite
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    # When a brokerage link was last started from this client's page and has
    # not yet shown up at the source. The source does not say who a new link
    # is for, so this is how it is filed under the right client.
    brokerage_link_started_at = Column(DateTime(timezone=True))

    accounts = relationship(
        "Account", back_populates="client", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Client(id={self.id}, name={self.name}, email={self.email})>"
