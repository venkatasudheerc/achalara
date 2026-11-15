"""Account model - represents a sub-portfolio within a client"""
from sqlalchemy import Column, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import relationship
import uuid
from app.models.base import BaseModel


class Account(BaseModel):
    """Represents a client account (sub-portfolio)"""

    __tablename__ = "accounts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # The first owner. Every owner, this one included, has a row in
    # ``account_owners``; this column stays as the account's main owner.
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
    # A custodial account is owned by its custodian and held "for" a minor, who
    # does not own it: they see it read-only if they sign in.
    beneficiary_id = Column(
        String(36), ForeignKey("clients.id", ondelete="SET NULL"), index=True
    )
    # The client who linked it. Until one of its owners signs in, they control
    # it (share, rename, change owner) on the owner's behalf.
    linked_by_id = Column(String(36), ForeignKey("clients.id", ondelete="SET NULL"))
    # The owner's own name for it ("Pat's trading account"), shown in place of
    # the custodian's name, which stays in ``name``. Empty when none is given.
    display_name = Column(String(60))

    # Relationships
    client = relationship("Client", back_populates="accounts", foreign_keys=[client_id])
    beneficiary = relationship("Client", foreign_keys=[beneficiary_id])
    owners = relationship(
        "AccountOwner", cascade="all, delete-orphan", back_populates="account"
    )
    sleeves = relationship(
        "Sleeve", back_populates="account", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Account(id={self.id}, name={self.name}, client_id={self.client_id})>"


class AccountOwner(BaseModel):
    """One owner of an account. A joint account has several, with equal rights."""

    __tablename__ = "account_owners"
    __table_args__ = (UniqueConstraint("account_id", "client_id", name="uq_account_owner"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id = Column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )

    account = relationship("Account", back_populates="owners")
    client = relationship("Client")


from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


@event.listens_for(Session, "before_flush")
def _new_accounts_have_an_owner(session, flush_context, instances):
    """Whoever an account is created for owns it, and linked it, unless set
    otherwise: every creator (a link, a test, a script) gets the same rule."""
    for account in list(session.new):
        if isinstance(account, Account) and account.client_id:
            if account.linked_by_id is None:
                account.linked_by_id = account.client_id
            if not any(o.client_id == account.client_id for o in account.owners):
                account.owners.append(AccountOwner(client_id=account.client_id))
