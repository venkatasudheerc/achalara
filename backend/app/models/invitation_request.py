"""A visitor's request for an invitation, left on the public page"""
from sqlalchemy import Column, DateTime, String
import uuid
from app.models.base import BaseModel

STATUS_NEW = "new"
STATUS_CONTACTED = "contacted"
STATUS_DISMISSED = "dismissed"
STATUSES = (STATUS_NEW, STATUS_CONTACTED, STATUS_DISMISSED)


class InvitationRequest(BaseModel):
    """Someone who is not a client asking to be one.

    Written by anyone on the internet, so it holds only what the form asks
    for, within length limits, and is linked to nothing. An adviser reads it
    and decides; becoming a client is a separate step taken by hand.
    """

    __tablename__ = "invitation_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(120), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(40), nullable=False)
    # Why they are interested and how they came to hear of Achalara.
    note = Column(String(1000), nullable=False)
    status = Column(String(20), nullable=False, default=STATUS_NEW)
    handled_at = Column(DateTime(timezone=True))
    # A request counts once the visitor has followed the link emailed to them,
    # which proves the address is theirs. Until then it is not shown or
    # alerted, and only a digest of the link's token is kept.
    confirmed_at = Column(DateTime(timezone=True))
    confirm_token_hash = Column(String(64), index=True)

    def __repr__(self):
        return f"<InvitationRequest(id={self.id}, status={self.status})>"
