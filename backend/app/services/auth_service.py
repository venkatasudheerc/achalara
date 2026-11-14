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
from app.services import mailer
from app.models.account import Account
from app.models.client import Client
from app.models.user import (
    PURPOSE_INVITE,
    PURPOSE_RESET,
    ROLE_ADMIN,
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
    """The last four digits of the institution's own number for the account, as
    the owner sees them on statements: the ones recorded when it was linked,
    else those of the full number the brokerage puts in its name, else those of
    the stored account number (a feed's own numbering, which can differ)."""
    if getattr(account, "last_four", None):
        return account.last_four
    in_name = re.findall(r"\d{6,}", account.name or "")
    if in_name:
        return in_name[-1][-4:]
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

    def create_admin(self, email: str, name: str, password: str) -> User:
        email = email.strip().lower()
        if self.user_by_email(email):
            raise AuthError(409, "A user with that email already exists.")
        problems = password_problems(password, email)
        if problems:
            raise AuthError(422, " ".join(problems))
        user = User(
            email=email,
            name=name.strip() or email,
            role=ROLE_ADMIN,
            password_hash=hash_password(password),
        )
        self.db.add(user)
        self.db.commit()
        return user

    def invite_advisor(self, email: str, name: str) -> Tuple[str, AuthToken]:
        """An advisor's login and a link to set its password. Only an admin
        may call this (the route guards it)."""
        user = User(email=self._free_email(email), name=name.strip() or email, role=ROLE_ADVISOR)
        self.db.add(user)
        self.db.flush()
        return self._issue(user, PURPOSE_INVITE, timedelta(days=INVITE_DAYS))

    # -- who manages whom ----------------------------------------------

    def manages(self, user: User, client_id: str) -> bool:
        """An admin manages every client; an advisor those assigned to them."""
        if user.role == ROLE_ADMIN:
            return True
        if user.role != ROLE_ADVISOR:
            return False
        client = self.db.get(Client, client_id)
        return client is not None and client.advisor_id == user.id

    def managed_clients(self, user: User) -> List[Client]:
        query = self.db.query(Client).order_by(Client.name)
        if user.role == ROLE_ADVISOR:
            query = query.filter(Client.advisor_id == user.id)
        elif user.role != ROLE_ADMIN:
            return []
        return query.all()

    # -- spouses and minors --------------------------------------------

    def set_spouse(self, client_id: str, spouse_id: Optional[str]) -> Client:
        """Make two clients each other's spouse, or end it (``spouse_id`` None).
        Neither may be a minor or already married to someone else."""
        client = self._client(client_id)
        if spouse_id is None:
            if client.spouse_id:
                other = self.db.get(Client, client.spouse_id)
                if other is not None and other.spouse_id == client.id:
                    other.spouse_id = None
            client.spouse_id = None
            self.db.commit()
            return client
        spouse = self._client(spouse_id)
        if spouse.id == client.id:
            raise AuthError(422, "A client cannot be their own spouse.")
        if client.is_minor or spouse.is_minor:
            raise AuthError(422, "A minor cannot have a spouse here.")
        for one, other in ((client, spouse), (spouse, client)):
            if one.spouse_id and one.spouse_id != other.id:
                raise AuthError(409, f"{one.name} already has a spouse.")
        client.spouse_id, spouse.spouse_id = spouse.id, client.id
        self.db.commit()
        return client

    def set_guardian(self, client_id: str, guardian_id: Optional[str]) -> Client:
        """Mark a client a minor in an adult client's care, or no longer a minor."""
        client = self._client(client_id)
        if guardian_id is not None:
            guardian = self._client(guardian_id)
            if guardian.is_minor or guardian.id == client.id:
                raise AuthError(422, "A guardian must be another adult client.")
            if client.spouse_id:
                raise AuthError(422, "A client with a spouse cannot be a minor.")
        client.guardian_id = guardian_id
        self.db.commit()
        return client

    def add_relative(
        self, client_id: str, name: str, relation: str, email: Optional[str] = None
    ) -> Client:
        """A new client who is ``client_id``'s spouse or minor, with the same
        advisor. A client may add their own; an admin or advisor anyone's."""
        client = self._client(client_id)
        if client.is_minor:
            raise AuthError(422, "A minor cannot add family members.")
        if relation not in ("spouse", "minor"):
            raise AuthError(422, "Add a spouse or a minor.")
        email = (email or "").strip().lower() or None
        if email and self.db.query(Client).filter(Client.email == email).first():
            raise AuthError(409, "A client with that email already exists.")
        relative = Client(name=name.strip(), email=email, advisor_id=client.advisor_id)
        if not relative.name:
            raise AuthError(422, "Give a name.")
        self.db.add(relative)
        self.db.flush()
        if relation == "spouse":
            self.set_spouse(client.id, relative.id)
        else:
            self.set_guardian(relative.id, client.id)
        return relative

    def relatives(self, client_id: str) -> List[Tuple[Client, str]]:
        """The client's spouse and minors (theirs and their spouse's), as
        ``(client, relation)``."""
        client = self._client(client_id)
        out: List[Tuple[Client, str]] = []
        if client.spouse_id:
            spouse = self.db.get(Client, client.spouse_id)
            if spouse is not None:
                out.append((spouse, "spouse"))
        guardians = [client.id] + ([client.spouse_id] if client.spouse_id else [])
        for minor in (
            self.db.query(Client).filter(Client.guardian_id.in_(guardians)).order_by(Client.name)
        ):
            out.append((minor, "minor"))
        return out

    def _client(self, client_id: str) -> Client:
        client = self.db.get(Client, client_id)
        if client is None:
            raise AuthError(404, "Client not found")
        return client

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

    def email_link(self, token: str) -> Tuple[bool, str]:
        """Email an unused link to the person it is for; (whether sent, the address).

        The link goes only to the login's own sign-in email, never to an
        address given with the request.
        """
        record = self._open_link(token)
        user = record.user
        route = "invite" if record.purpose == PURPOSE_INVITE else "reset"
        message = mailer.link_message(
            user.name,
            user.email,
            record.purpose,
            f"/{route}/{token}",
            record.expires_at,
        )
        return mailer.send(message), user.email

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
        """A client user's accounts as ``(account, shared)``; none for an admin or advisor."""
        if user.role != ROLE_CLIENT:
            return []
        return self.accounts_for_client(user.client_id)

    def accounts_for_client(self, client_id: str) -> List[Tuple[Account, bool]]:
        """What a client may view, as ``(account, shared)``, by the guardrails:

        1. their own accounts;
        2. their spouse's, except those the spouse keeps private;
        3. for a guardian and the guardian's spouse, every account of their
           minors (a minor cannot keep one from them);
        4. a minor sees only their own (and anything shared with them);
        5. anything else only when shared with them (``account_access``).
        """
        own = (
            self.db.query(Account)
            .filter(Account.client_id == client_id)
            .order_by(Account.name)
            .all()
        )
        client = self.db.get(Client, client_id)
        seen = {a.id for a in own}
        family: List[Account] = []
        if client is not None and not client.is_minor:
            if client.spouse_id:
                family += (
                    self.db.query(Account)
                    .filter(Account.client_id == client.spouse_id, Account.is_private.is_(False))
                    .order_by(Account.name)
                    .all()
                )
            guardians = [client.id] + ([client.spouse_id] if client.spouse_id else [])
            minors = [
                row[0]
                for row in self.db.query(Client.id).filter(Client.guardian_id.in_(guardians))
            ]
            if minors:
                family += (
                    self.db.query(Account)
                    .filter(Account.client_id.in_(minors))
                    .order_by(Account.name)
                    .all()
                )
        family = [a for a in family if not (a.id in seen or seen.add(a.id))]
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
        granted = [a for a in granted if a.id not in seen]
        return [(a, False) for a in own] + [(a, True) for a in family + granted]

    def can_read_account(self, user: User, client_id: str, account_id: str) -> bool:
        """Whether ``user`` may read the account at ``/clients/{client_id}/accounts/{account_id}``."""
        account = (
            self.db.query(Account)
            .filter(Account.id == account_id, Account.client_id == client_id)
            .first()
        )
        if account is None:
            return False
        if user.role in (ROLE_ADMIN, ROLE_ADVISOR):
            return self.manages(user, client_id)
        return any(a.id == account_id for a, _ in self.accounts_for_client(user.client_id))

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
