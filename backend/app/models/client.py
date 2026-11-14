"""Client model"""
from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship
import uuid
from app.models.base import BaseModel


class Client(BaseModel):
    """Client account"""

    __tablename__ = "clients"

    # Use string for UUID to work with both PostgreSQL and SQLite
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    # A minor may have none.
    email = Column(String(255), unique=True, nullable=True)
    # The advisor who manages this client (a ``users`` row of role advisor);
    # none when only the admin manages them.
    advisor_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    # Who sees what follows from these (``AuthService.accounts_for_client``):
    # spouses see each other's accounts unless one is private; a minor's
    # guardian, and the guardian's spouse, see the minor's accounts.
    # ``spouse_id`` is kept in pairs: each names the other.
    spouse_id = Column(String(36), ForeignKey("clients.id", ondelete="SET NULL"))
    # Set for a minor: the adult client responsible for them.
    guardian_id = Column(
        String(36), ForeignKey("clients.id", ondelete="SET NULL"), index=True
    )
    # When a brokerage link was last started from this client's page and has
    # not yet shown up at the source. The source does not say who a new link
    # is for, so this is how it is filed under the right client.
    brokerage_link_started_at = Column(DateTime(timezone=True))

    accounts = relationship(
        "Account", back_populates="client", cascade="all, delete-orphan"
    )

    @property
    def is_minor(self) -> bool:
        return self.guardian_id is not None

    def __repr__(self):
        return f"<Client(id={self.id}, name={self.name}, email={self.email})>"
