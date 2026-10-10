"""Brokerage connection models — a linked login and the accounts under it"""
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
import uuid
from app.models.base import BaseModel


class BrokerageConnection(BaseModel):
    """One brokerage login a client authorized through an aggregator.

    Holds only references the aggregator hands back — never credentials. The
    Personal SnapTrade flow issues no per-user secret, so there is nothing
    secret to store here.
    """

    __tablename__ = "brokerage_connections"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    source = Column(String(50), nullable=False)  # connector registry name
    external_user_id = Column(String(255), nullable=False)
    external_connection_id = Column(String(255), nullable=False)
    institution = Column(String(255), nullable=False, default="")
    status = Column(String(20), nullable=False, default="active")

    __table_args__ = (
        UniqueConstraint(
            "source", "external_connection_id", name="uq_connection_source_external"
        ),
    )

    brokerage_accounts = relationship(
        "BrokerageAccount", back_populates="connection", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<BrokerageConnection(id={self.id}, source={self.source}, "
            f"institution={self.institution}, status={self.status})>"
        )


class BrokerageAccount(BaseModel):
    """An account discovered under a connection, whether or not it is mapped.

    Separate from ``Account`` because one login exposes several accounts at
    once and some are never brought into Achalara. Mapping one sets
    ``account_id`` and the ``default_sleeve_id`` its trades are ingested into.
    """

    __tablename__ = "brokerage_accounts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id = Column(
        String(36),
        ForeignKey("brokerage_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_account_ref = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    number_last4 = Column(String(4))
    account_id = Column(String(36), ForeignKey("accounts.id", ondelete="SET NULL"))
    default_sleeve_id = Column(
        String(36), ForeignKey("sleeves.id", ondelete="SET NULL")
    )
    status = Column(String(20), nullable=False, default="unmapped")
    # The source's own report of how far its transaction history is complete.
    # This, not our clock, is the watermark: transactions lag holdings by days.
    initial_sync_completed = Column(Boolean, nullable=False, default=False)
    transactions_synced_through = Column(Date)
    last_synced_at = Column(DateTime(timezone=True))
    last_reconciled_at = Column(DateTime(timezone=True))
    reconciliation = Column(JSON)

    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "external_account_ref",
            name="uq_brokerage_account_connection_ref",
        ),
    )

    connection = relationship(
        "BrokerageConnection", back_populates="brokerage_accounts"
    )

    account = relationship("Account")

    @property
    def owner_client_id(self):
        """The client who owns the mapped account, which may not be the one
        whose login reaches it."""
        return self.account.client_id if self.account is not None else None

    def __repr__(self):
        return (
            f"<BrokerageAccount(id={self.id}, name={self.name}, "
            f"status={self.status})>"
        )
