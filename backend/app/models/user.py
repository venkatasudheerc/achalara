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

# The platform's super user: everything, everyone.
ROLE_ADMIN = "admin"
# Manages the clients assigned to them (``clients.advisor_id``), and only those.
# Only an admin creates an advisor.
ROLE_ADVISOR = "advisor"
# A person with their own accounts: an adult (who may have a spouse) or a minor.
ROLE_CLIENT = "client"
ROLES = (ROLE_ADMIN, ROLE_ADVISOR, ROLE_CLIENT)

PURPOSE_INVITE = "invite"
PURPOSE_RESET = "reset"


def _uuid() -> str:
    return str(uuid.uuid4())


class User(BaseModel):
    """A login. An admin sees everything; an advisor sees the clients assigned to
    them; a client user belongs to one Client.

    ``password_hash`` is NULL until the person sets a password from their
    invite, and such a user cannot sign in.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'advisor', 'client')", name="user_role"),
        # A client login always names its client; an admin or advisor never does.
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

    client = relationship("Client", foreign_keys=[client_id])

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


# What a share allows. Only viewing exists; transacting is to come, and is
# stored in the same column so adding it needs no model change.
LEVEL_VIEW = "view"
LEVELS = (LEVEL_VIEW,)


class AccountAccess(BaseModel):
    """Someone an owner has shared an account with: a client, or the client's
    advisor (a login, ``user_id``). Nobody else sees an account until it is
    shared. The owners need no row here (``account_owners``)."""

    __tablename__ = "account_access"
    __table_args__ = (
        UniqueConstraint("client_id", "account_id", name="uq_account_access"),
        UniqueConstraint("user_id", "account_id", name="uq_account_access_user"),
        CheckConstraint(
            "(client_id IS NULL) != (user_id IS NULL)", name="account_access_one_grantee"
        ),
        CheckConstraint("level IN ('view')", name="account_access_level"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    client_id = Column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id = Column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    level = Column(String(10), nullable=False, default=LEVEL_VIEW, server_default=LEVEL_VIEW)
    # Hidden from the grantee's own screens by them ("Stop seeing"); the owner
    # is not told.
    hidden = Column(Boolean, nullable=False, default=False, server_default="false")

    client = relationship("Client", foreign_keys=[client_id])
    user = relationship("User", foreign_keys=[user_id])
    account = relationship("Account")
