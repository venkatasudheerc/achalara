"""Client schemas"""
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID  # noqa: F401
from datetime import datetime
from typing import Optional  # noqa: F401


class ClientCreate(BaseModel):
    """Create client request"""

    name: str
    email: EmailStr


class ClientResponse(BaseModel):
    """Client response"""

    id: str = Field(..., description="Client UUID")
    name: str
    email: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
