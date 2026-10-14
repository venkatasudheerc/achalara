"""Client schemas"""
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID  # noqa: F401
from datetime import datetime
from typing import Optional


class ClientCreate(BaseModel):
    """Create client request"""

    name: str
    email: EmailStr


class ClientUpdate(BaseModel):
    """Correct a client's name or contact email; a field left out is kept.

    The contact email is the client record's own. The email a client signs in
    with belongs to their login and is changed there.
    """

    name: Optional[str] = Field(None, min_length=1)
    email: Optional[EmailStr] = None


class ClientResponse(BaseModel):
    """Client response"""

    id: str = Field(..., description="Client UUID")
    name: str
    email: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
