"""Who can sign in, their sessions, one-time links, and shared-account grants."""
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base import BaseModel

ROLE_ADVISOR = "advisor"
ROLE_CLIENT = "client"

PURPOSE_INVITE = "invite"
PURPOSE_RESET = "reset"


def _uuid() -> str:
    return str(uuid.uuid4())


class User(BaseModel):
    """A login. An advisor sees everything; a client user belongs to one Client.

    ``password_hash`` is NULL until the person sets a password from their
    invite, and such a user cannot sign in.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('advisor', 'client')", name="user_role"),
        # A client login always names its client; an advisor never does.
        CheckConstraint(
            "(role = 'client') = (client_id IS NOT NULL)",
            name="user_client_matches_role",
        ),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False)  # stored lower-case
    name = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False)
    # One login per client.
    client_id = Column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), unique=True
    )
    password_hash = Column(String(255))
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    failed_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True))
    last_login_at = Column(DateTime(timezone=True))

    client = relationship("Client")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"


class UserSession(BaseModel):
    """A signed-in browser. Only a digest of the cookie's token is stored."""

    __tablename__ = "user_sessions"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User")


class AuthToken(BaseModel):
    """A one-time link: an invite to set a first password, or a reset.

    Only a digest of the link's token is stored, so a copy of the table cannot
    be used to accept an invite.
    """

    __tablename__ = "auth_tokens"
    __table_args__ = (
        CheckConstraint("purpose IN ('invite', 'reset')", name="auth_token_purpose"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose = Column(String(20), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True))

    user = relationship("User")


class AccountAccess(BaseModel):
    """A client allowed to view an account that belongs to another client.

    The account's owner is ``accounts.client_id`` and needs no row here; this
    table holds only the extra viewers (for example someone acting as agent on
    a relative's account). Access is read-only.
    """

    __tablename__ = "account_access"
    __table_args__ = (
        UniqueConstraint("client_id", "account_id", name="uq_account_access"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    client_id = Column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id = Column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    client = relationship("Client")
    account = relationship("Account")
