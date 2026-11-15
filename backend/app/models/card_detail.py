"""What a card's issuer says about the card itself: limits and what is due"""
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Numeric, String

from app.models.base import BaseModel


class CardDetail(BaseModel):
    """A credit card's limit, available credit, cash advance limit and payment
    due, as the institution last reported them through Plaid.

    One row per card account, replaced each morning by the Plaid refresh. Any
    figure can be empty: what an institution sends varies, and a card with
    nothing owed has no payment due. The card's balance is not here (it is the
    account's recorded value); nothing in ``perf`` reads this table. It holds
    no account number and no credentials.
    """

    __tablename__ = "card_details"

    account_id = Column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    credit_limit = Column(Numeric(18, 2))
    available_credit = Column(Numeric(18, 2))
    cash_advance_limit = Column(Numeric(18, 2))
    minimum_payment = Column(Numeric(18, 2))
    next_payment_due_date = Column(Date)
    last_payment_amount = Column(Numeric(18, 2))
    last_payment_date = Column(Date)
    last_statement_balance = Column(Numeric(18, 2))
    is_overdue = Column(Boolean)
    refreshed_at = Column(DateTime(timezone=True), nullable=False)
