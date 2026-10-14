"""Invitation request schemas"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class InvitationRequestCreate(BaseModel):
    """What the public form sends."""

    name: str = Field(..., max_length=120)
    email: EmailStr
    phone: str = Field(..., max_length=40)
    # Why they are interested and how they came to hear of Achalara.
    note: str = Field(..., max_length=1000)
    # Hidden on the page; a person leaves it empty.
    website: Optional[str] = Field(None, max_length=200)

    @field_validator("name", "note")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("This is needed")
        return value

    @field_validator("phone")
    @classmethod
    def _a_phone_number(cls, value: str) -> str:
        """Digits with the usual punctuation, in any country's layout."""
        value = " ".join(value.split())
        digits = [ch for ch in value if ch.isdigit()]
        if not 7 <= len(digits) <= 15 or any(
            not (ch.isdigit() or ch in "+-.() ") for ch in value
        ):
            raise ValueError("Enter a phone number")
        return value


class InvitationRequestReceived(BaseModel):
    """The same answer whatever became of the request."""

    received: bool = True


class InvitationRequestResponse(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    note: str
    status: str  # new | contacted | dismissed
    created_at: datetime
    handled_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class InvitationRequestUpdate(BaseModel):
    status: Literal["new", "contacted", "dismissed"]
