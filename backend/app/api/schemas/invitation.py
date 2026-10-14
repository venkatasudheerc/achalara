"""Invitation request schemas"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.services import email_domains

MIN_PHONE_DIGITS = 10
MIN_NOTE_LENGTH = 50
MIN_NOTE_WORDS = 6


class InvitationRequestCreate(BaseModel):
    """What the public form sends."""

    name: str = Field(..., max_length=120)
    email: EmailStr
    phone: str = Field(..., max_length=40)
    # Why they are interested and how they came to hear of Achalara.
    note: str = Field(..., max_length=1000)
    # Hidden on the page; a person leaves it empty.
    website: Optional[str] = Field(None, max_length=200)

    @field_validator("name")
    @classmethod
    def _a_name(cls, value: str) -> str:
        """Letters, with the spaces, dots, apostrophes and hyphens names have."""
        value = " ".join(value.split())
        letters = [ch for ch in value if ch.isalpha()]
        if len(letters) < 2 or any(not (ch.isalpha() or ch in " .'-") for ch in value):
            raise ValueError("Enter your name")
        return value

    @field_validator("email")
    @classmethod
    def _a_mailbox(cls, value: str) -> str:
        if not email_domains.receives_mail(value):
            raise ValueError("That email address cannot receive mail")
        return value

    @field_validator("phone")
    @classmethod
    def _a_phone_number(cls, value: str) -> str:
        """10 to 15 digits with the usual punctuation, in any country's layout.

        Not one digit over and over, and not a plain run such as 1234567890.
        """
        value = " ".join(value.split())
        digits = "".join(ch for ch in value if ch.isdigit())
        if not MIN_PHONE_DIGITS <= len(digits) <= 15 or any(
            not (ch.isdigit() or ch in "+-.() ") for ch in value
        ):
            raise ValueError("Enter a phone number")
        if len(set(digits)) == 1 or digits in "01234567890" or digits in "9876543210":
            raise ValueError("Enter a phone number")
        return value

    @field_validator("note")
    @classmethod
    def _a_real_answer(cls, value: str) -> str:
        """At least MIN_NOTE_LENGTH characters, made of words."""
        value = " ".join(value.split())
        words = [w for w in value.split(" ") if any(ch.isalpha() for ch in w)]
        if len(value) < MIN_NOTE_LENGTH or len(words) < MIN_NOTE_WORDS:
            raise ValueError(
                f"Tell us a little more: at least {MIN_NOTE_LENGTH} characters"
            )
        return value


class InvitationRequestReceived(BaseModel):
    """The same answer whatever became of the request."""

    received: bool = True
    # Whether the visitor should look for an email to confirm the request. The
    # same for every request on a server, so it says nothing about this one.
    confirm_by_email: bool = False


class InvitationConfirm(BaseModel):
    token: str = Field(..., max_length=200)


class InvitationConfirmed(BaseModel):
    confirmed: bool = True


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
