"""Sign-in, sessions, one-time links, and who may see which account.

Passwords are hashed with scrypt. Session and link tokens are random and only
their SHA-256 digest is stored, so neither can be recovered from the database.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.models.account import Account
from app.models.client import Client
from app.models.user import (
    PURPOSE_INVITE,
    PURPOSE_RESET,
    ROLE_ADVISOR,
    ROLE_CLIENT,
    AccountAccess,
    AuthToken,
    User,
    UserSession,
)

SESSION_COOKIE = "achalara_session"
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
INVITE_DAYS = 7
RESET_HOURS = 24
MIN_PASSWORD_LENGTH = 12

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
_BAD_CREDENTIALS = "That email and password don't match."


class AuthError(Exception):
    """A refusal the caller should see, with the HTTP status it maps to."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(moment: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes; they were stored as UTC."""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    try:
        scheme, n, r, p, salt, key = (stored or "").split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(key)
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Verified against when the email is unknown, so a wrong email takes as long
# as a wrong password and the two cannot be told apart by timing.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def password_problems(password: str, email: str) -> List[str]:
    """Why ``password`` is not acceptable; empty when it is."""
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        problems.append("Include a letter and a number.")
    local_part = email.split("@")[0].lower()
    if local_part and local_part in password.lower():
        problems.append("Don't use your email address.")
    return problems


def last_four(account: Account) -> Optional[str]:
    digits = re.sub(r"\D", "", account.account_number or "")
    return digits[-4:] if len(digits) >= 4 else None


def display_name(account: Account) -> str:
    """The account's name without any full account number in it."""
    cleaned = re.sub(r"\s*[—–-]\s*\d{6,}\b", "", account.name)
    return re.sub(r"\b\d{6,}\b", "", cleaned).strip(" —–-") or account.name


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    # -- users ---------------------------------------------------------

    def user_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(User.email == email.strip().lower()).first()

    def users(self) -> List[User]:
        return self.db.query(User).order_by(User.role, User.email).all()

    def create_advisor(self, email: str, name: str, password: str) -> User:
        email = email.strip().lower()
        if self.user_by_email(email):
            raise AuthError(409, "A user with that email already exists.")
        problems = password_problems(password, email)
        if problems:
            raise AuthError(422, " ".join(problems))
        user = User(
            email=email,
            name=name.strip() or email,
            role=ROLE_ADVISOR,
            password_hash=hash_password(password),
        )
        self.db.add(user)
        self.db.commit()
        return user

    # -- sign-in and sessions ------------------------------------------

    def login(self, email: str, password: str) -> Tuple[User, str]:
        user = self.user_by_email(email)
        if user is None or not user.is_active or not user.password_hash:
            verify_password(password, _DUMMY_HASH)
            raise AuthError(401, _BAD_CREDENTIALS)

        locked_until = _aware(user.locked_until)
        if locked_until and locked_until > _now():
            minutes = max(1, int((locked_until - _now()).total_seconds() // 60) + 1)
            raise AuthError(429, f"Too many attempts. Try again in {minutes} minutes.")

        if not verify_password(password, user.password_hash):
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = _now() + timedelta(minutes=LOCK_MINUTES)
                user.failed_attempts = 0
            self.db.commit()
            raise AuthError(401, _BAD_CREDENTIALS)

        user.failed_attempts = 0
        user.locked_until = None
        user.last_login_at = _now()
        token = self._open_session(user)
        self.db.commit()
        return user, token

    def _open_session(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        self.db.add(
            UserSession(
                user_id=user.id,
                token_hash=_digest(token),
                expires_at=_now() + timedelta(hours=settings.session_ttl_hours),
            )
        )
        return token

    def user_for_session(self, token: Optional[str]) -> Optional[User]:
        if not token:
            return None
        session = (
            self.db.query(UserSession)
            .filter(UserSession.token_hash == _digest(token))
            .first()
        )
        if session is None or _aware(session.expires_at) <= _now():
            return None
        return session.user if session.user.is_active else None

    def logout(self, token: Optional[str]) -> None:
        if not token:
            return
        self.db.query(UserSession).filter(
            UserSession.token_hash == _digest(token)
        ).delete()
        self.db.commit()

    def change_password(self, user: User, current: str, new: str) -> str:
        """Set a new password and return a fresh session; other sessions end."""
        if not verify_password(current, user.password_hash):
            raise AuthError(401, "Your current password is not correct.")
        return self._set_password(user, new)

    def _set_password(self, user: User, password: str) -> str:
        problems = password_problems(password, user.email)
        if problems:
            raise AuthError(422, " ".join(problems))
        user.password_hash = hash_password(password)
        user.failed_attempts = 0
        user.locked_until = None
        # Whoever held a session under the old password is signed out.
        self.db.query(UserSession).filter(UserSession.user_id == user.id).delete()
        token = self._open_session(user)
        self.db.commit()
        return token

    # -- one-time links ------------------------------------------------

    def _free_email(self, email: str, user: Optional[User] = None) -> str:
        """``email`` normalised, or a refusal if another login already uses it."""
        email = email.strip().lower()
        holder = self.user_by_email(email)
        if holder is not None and (user is None or holder.id != user.id):
            raise AuthError(
                409,
                f"Another login already uses {email}. Choose a different sign-in email.",
            )
        return email

    def invite_client(
        self, client_id: str, email: Optional[str] = None
    ) -> Tuple[str, AuthToken]:
        """Create (or reuse) the client's login and a link to set its password.

        The sign-in email is the advisor's to choose; it defaults to the
        client's own. Inviting again before the first link is used may correct
        the address.
        """
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if client is None:
            raise AuthError(404, "Client not found")
        user = self.db.query(User).filter(User.client_id == client_id).first()
        if user is None:
            user = User(
                email=self._free_email(email or client.email),
                name=client.name,
                role=ROLE_CLIENT,
                client_id=client_id,
            )
            self.db.add(user)
            self.db.flush()
        elif user.password_hash:
            raise AuthError(
                409, "This client already has a login. Send a password reset instead."
            )
        elif email:
            user.email = self._free_email(email, user)
        return self._issue(user, PURPOSE_INVITE, timedelta(days=INVITE_DAYS))

    def change_email(self, user_id: str, email: str) -> Tuple[str, AuthToken]:
        """Give a client's login a new sign-in email, and a link to send them.

        The old address stops working at once and the client is signed out
        everywhere. A password already set is kept, so the new address works
        straight away; the link (a reset, or a fresh invite if no password was
        ever set) is there for the advisor to pass on.
        """
        user = self.db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise AuthError(404, "User not found")
        if user.role != ROLE_CLIENT:
            raise AuthError(422, "Only a client's sign-in email is changed here.")
        user.email = self._free_email(email, user)
        self.db.query(UserSession).filter(UserSession.user_id == user.id).delete()
        if user.password_hash:
            return self._issue(user, PURPOSE_RESET, timedelta(hours=RESET_HOURS))
        return self._issue(user, PURPOSE_INVITE, timedelta(days=INVITE_DAYS))

    def reset_link(self, user_id: str) -> Tuple[str, AuthToken]:
        user = self.db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise AuthError(404, "User not found")
        return self._issue(user, PURPOSE_RESET, timedelta(hours=RESET_HOURS))

    def _issue(
        self, user: User, purpose: str, lifetime: timedelta
    ) -> Tuple[str, AuthToken]:
        # A new link replaces any earlier unused one of the same kind.
        self.db.query(AuthToken).filter(
            AuthToken.user_id == user.id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
        ).delete()
        token = secrets.token_urlsafe(32)
        record = AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=_digest(token),
            expires_at=_now() + lifetime,
        )
        self.db.add(record)
        self.db.commit()
        return token, record

    def _open_link(self, token: str) -> AuthToken:
        record = (
            self.db.query(AuthToken)
            .filter(AuthToken.token_hash == _digest(token))
            .first()
        )
        if (
            record is None
            or record.used_at is not None
            or _aware(record.expires_at) <= _now()
            or not record.user.is_active
        ):
            # One answer for unknown, used and expired: the link reveals nothing.
            raise AuthError(404, "This link is no longer valid. Ask for a new one.")
        return record

    def link_user(self, token: str) -> Tuple[AuthToken, User]:
        record = self._open_link(token)
        return record, record.user

    def accept_link(self, token: str, password: str) -> Tuple[User, str]:
        """Set the password a link was issued for and sign the person in."""
        record = self._open_link(token)
        user = record.user
        session_token = self._set_password(user, password)
        record.used_at = _now()
        user.last_login_at = _now()
        self.db.commit()
        return user, session_token

    # -- who may see what ----------------------------------------------

    def accessible_accounts(self, user: User) -> List[Tuple[Account, bool]]:
        """A client user's accounts as ``(account, shared)``; none for an advisor."""
        if user.role != ROLE_CLIENT:
            return []
        return self.accounts_for_client(user.client_id)

    def accounts_for_client(self, client_id: str) -> List[Tuple[Account, bool]]:
        """What a client may view, as ``(account, shared)``: their own accounts
        first, then those of other clients they have been granted."""
        own = (
            self.db.query(Account)
            .filter(Account.client_id == client_id)
            .order_by(Account.name)
            .all()
        )
        granted = (
            self.db.query(Account)
            .join(AccountAccess, AccountAccess.account_id == Account.id)
            .filter(
                AccountAccess.client_id == client_id,
                Account.client_id != client_id,
            )
            .order_by(Account.name)
            .all()
        )
        return [(a, False) for a in own] + [(a, True) for a in granted]

    def can_read_account(self, user: User, client_id: str, account_id: str) -> bool:
        """Whether ``user`` may read the account at ``/clients/{client_id}/accounts/{account_id}``."""
        if user.role == ROLE_ADVISOR:
            return True
        account = (
            self.db.query(Account)
            .filter(Account.id == account_id, Account.client_id == client_id)
            .first()
        )
        if account is None:
            return False
        if account.client_id == user.client_id:
            return True
        return (
            self.db.query(AccountAccess)
            .filter(
                AccountAccess.client_id == user.client_id,
                AccountAccess.account_id == account_id,
            )
            .first()
            is not None
        )

    def grants(self, client_id: str) -> List[AccountAccess]:
        return (
            self.db.query(AccountAccess)
            .filter(AccountAccess.client_id == client_id)
            .all()
        )

    def grant(self, client_id: str, account_id: str) -> AccountAccess:
        if self.db.query(Client).filter(Client.id == client_id).first() is None:
            raise AuthError(404, "Client not found")
        account = self.db.query(Account).filter(Account.id == account_id).first()
        if account is None:
            raise AuthError(404, "Account not found")
        if account.client_id == client_id:
            raise AuthError(422, "The client already owns this account.")
        existing = (
            self.db.query(AccountAccess)
            .filter(
                AccountAccess.client_id == client_id,
                AccountAccess.account_id == account_id,
            )
            .first()
        )
        if existing:
            return existing
        access = AccountAccess(client_id=client_id, account_id=account_id)
        self.db.add(access)
        self.db.commit()
        return access

    def revoke(self, client_id: str, account_id: str) -> bool:
        removed = (
            self.db.query(AccountAccess)
            .filter(
                AccountAccess.client_id == client_id,
                AccountAccess.account_id == account_id,
            )
            .delete()
        )
        self.db.commit()
        return bool(removed)
