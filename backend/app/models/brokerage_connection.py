"""Brokerage connection models — a linked login and the accounts under it"""
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    false,
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
    # When the source was last asked about this link, and since when it has
    # reported it as no longer sharing data (empty while it is active).
    status_checked_at = Column(DateTime(timezone=True))
    disabled_at = Column(DateTime(timezone=True))

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
    # A digest of the brokerage and the account's full number, where the source
    # shows one. The same account reached through a second login has the same
    # value, which is how it is kept from being brought in twice.
    account_fingerprint = Column(String(64), index=True)
    account_id = Column(String(36), ForeignKey("accounts.id", ondelete="SET NULL"))
    default_sleeve_id = Column(
        String(36), ForeignKey("sleeves.id", ondelete="SET NULL")
    )
    status = Column(String(20), nullable=False, default="unmapped")
    # Security type -> sleeve id, for accounts split across strategies by what
    # is traded (e.g. {"ETF": "<sleeve>"}). Types without an entry go to
    # default_sleeve_id.
    sleeve_routes = Column(JSON)
    # Earliest activity date to pull. NULL means the full history.
    sync_start_date = Column(Date)
    # The source's own report of how far its transaction history is complete.
    # This, not our clock, is the watermark: transactions lag holdings by days.
    initial_sync_completed = Column(Boolean, nullable=False, default=False)
    transactions_synced_through = Column(Date)
    last_synced_at = Column(DateTime(timezone=True))
    last_reconciled_at = Column(DateTime(timezone=True))
    reconciliation = Column(JSON)
    # Cash the source last reported for the account, and when. With the cash
    # each stored activity moved, this gives the balance on any earlier date.
    cash_balance = Column(Numeric(18, 2))
    cash_balance_at = Column(DateTime(timezone=True))

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

    # Set by the service on an unmapped account that looks like one already
    # brought in; not stored.
    duplicate_of = None

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


class BrokerageActivity(BaseModel):
    """One activity row exactly as the source sent it.

    The trades and cash activities we keep are a simplified reading of these.
    Holding the originals means that reading can be redone — new handling for
    splits, say — without pulling from a source that limits how often we ask.
    Includes rows that were skipped, with the reason in ``outcome``.
    """

    __tablename__ = "brokerage_activities"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    brokerage_account_id = Column(
        String(36),
        ForeignKey("brokerage_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The source's id for the row. It can change if the source reprocesses the
    # activity, so it identifies a row for storage but is never a dedup key
    # for trades.
    source_activity_id = Column(String(255), nullable=False)
    activity_date = Column(Date)
    type = Column(String(50), nullable=False, default="")
    symbol = Column(String(50))
    outcome = Column(String(40), nullable=False)  # trade | cash | skipped:<reason>
    # Signed effect on the account's cash; see connectors.models.RawActivity.
    cash_amount = Column(Numeric(18, 2))
    is_external_flow = Column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    payload = Column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "brokerage_account_id",
            "source_activity_id",
            name="uq_brokerage_activity_account_source",
        ),
    )

    def __repr__(self):
        return (
            f"<BrokerageActivity(id={self.id}, type={self.type}, "
            f"outcome={self.outcome})>"
        )
