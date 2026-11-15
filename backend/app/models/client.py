"""Client model"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, UniqueConstraint
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
    # How people are related. Neither decides who sees an account: that is
    # only ownership and explicit shares (``AuthService.accounts_for_client``).
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

    # Set once by the migration to explicit shares, until the client has been
    # told ("Sam sees 3 of your accounts"); cleared when they dismiss it.
    sharing_notice = Column(Boolean, nullable=False, default=False, server_default="false")

    accounts = relationship(
        "Account",
        back_populates="client",
        cascade="all, delete-orphan",
        foreign_keys="Account.client_id",
    )

    @property
    def is_minor(self) -> bool:
        return self.guardian_id is not None

    def __repr__(self):
        return f"<Client(id={self.id}, name={self.name}, email={self.email})>"


# How one person describes another, from the first person's side.
RELATIONS = ("spouse", "minor", "child_grown", "parent", "friend", "other")
FAMILY_RELATIONS = ("spouse", "minor", "child_grown", "parent")


class PersonLink(BaseModel):
    """A person a client has added, and how they are related (the client's word
    for them). A spouse and a minor are also kept in ``spouse_id`` and
    ``guardian_id``; this table holds every relation, including friends."""

    __tablename__ = "person_links"
    __table_args__ = (UniqueConstraint("client_id", "person_id", name="uq_person_link"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_id = Column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    relation = Column(String(20), nullable=False)
