"""Sign-in, invite and account-sharing schemas"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PasswordRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class InviteRequest(BaseModel):
    client_id: str


class AccountAccessRequest(BaseModel):
    account_id: str


class VisibleAccount(BaseModel):
    """An account a client user may view. Never carries a full account number."""

    id: str
    client_id: str  # the owner, which is not the viewer when ``shared``
    name: str
    number_last4: Optional[str] = None
    shared: bool


class MeResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str  # advisor | client
    client_id: Optional[str] = None
    accounts: List[VisibleAccount] = []  # empty for an advisor, who sees all


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    client_id: Optional[str] = None
    is_active: bool
    has_password: bool
    last_login_at: Optional[datetime] = None


class LinkResponse(BaseModel):
    """A one-time link for the advisor to pass on. The token is shown once."""

    token: str
    path: str  # frontend route that accepts it
    purpose: str  # invite | reset
    email: str
    expires_at: datetime


class LinkPreview(BaseModel):
    """What the holder of a link sees before choosing a password."""

    purpose: str
    email: str
    name: str
    accounts: List[VisibleAccount] = []


class AccountAccessResponse(BaseModel):
    client_id: str
    account_id: str
    account_name: str
    owner_client_id: str
    owner_name: str
