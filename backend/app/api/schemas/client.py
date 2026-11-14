"""Client schemas"""
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID  # noqa: F401
from datetime import datetime
from typing import Optional


class ClientCreate(BaseModel):
    """Create client request. A minor may have no email. An advisor's new client
    is theirs; an admin may assign one to an advisor."""

    name: str
    email: Optional[EmailStr] = None
    advisor_id: Optional[str] = None


class ClientUpdate(BaseModel):
    """Correct a client's name or contact email; a field left out is kept.

    The contact email is the client record's own. The email a client signs in
    with belongs to their login and is changed there.
    """

    name: Optional[str] = Field(None, min_length=1)
    email: Optional[EmailStr] = None
    # Admin only. Sent as null, the client has no advisor.
    advisor_id: Optional[str] = None


class SpouseRequest(BaseModel):
    """Make this client and another each other's spouse; null ends it."""

    spouse_id: Optional[str] = None


class GuardianRequest(BaseModel):
    """Mark this client a minor in another client's care; null: not a minor."""

    guardian_id: Optional[str] = None


class RelativeCreate(BaseModel):
    """A new client who is this client's spouse or minor."""

    name: str = Field(..., min_length=1)
    relation: str = Field(..., pattern="^(spouse|minor)$")
    email: Optional[EmailStr] = None


class RelativeInvite(BaseModel):
    """The address a spouse or minor will sign in with; their own by default."""

    email: Optional[EmailStr] = None


class Relative(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    relation: str  # spouse | minor
    has_login: bool


class ClientResponse(BaseModel):
    """Client response"""

    id: str = Field(..., description="Client UUID")
    name: str
    email: Optional[str] = None
    advisor_id: Optional[str] = None
    spouse_id: Optional[str] = None
    # Set for a minor: the adult client responsible for them.
    guardian_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
