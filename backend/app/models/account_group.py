"""A client's own named groups of accounts, for the landing page's account list."""
import uuid

from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


def _uuid() -> str:
    return str(uuid.uuid4())


class AccountGroup(BaseModel):
    """A named set of accounts ("Retirement", "The kids") a client keeps for viewing.

    It belongs to the client whose portal it is, so an advisor previewing that
    portal sees the same groups. It changes nothing about who may see an account:
    members are only ever accounts the client can already see, and an account that
    stops being visible simply drops out when the group is read.
    """

    __tablename__ = "account_groups"
    __table_args__ = (
        UniqueConstraint("client_id", "name", name="uq_account_group_name"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    client_id = Column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(80), nullable=False)
    position = Column(Integer, nullable=False, default=0)

    members = relationship(
        "AccountGroupMember", cascade="all, delete-orphan", back_populates="group"
    )


class AccountGroupMember(BaseModel):
    """One account in a group."""

    __tablename__ = "account_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "account_id", name="uq_account_group_member"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    group_id = Column(
        String(36),
        ForeignKey("account_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id = Column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    group = relationship("AccountGroup", back_populates="members")
