"""Sign-in, one-time links, and sharing an account with another client"""
from contextlib import contextmanager
from typing import List, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_advisor
from app.api.schemas.auth import (
    AccountAccessRequest,
    AccountAccessResponse,
    ChangePasswordRequest,
    InviteRequest,
    LinkPreview,
    LinkResponse,
    LoginRequest,
    MeResponse,
    PasswordRequest,
    UserResponse,
    VisibleAccount,
)
from app.config import settings
from app.db.database import get_db
from app.models.user import PURPOSE_INVITE, AccountAccess, AuthToken, User
from app.services.auth_service import (
    SESSION_COOKIE,
    AuthError,
    AuthService,
    display_name,
    last_four,
)

router = APIRouter()
# Mounted with the data routes' access rule, which keeps these with the advisor.
access_router = APIRouter()


@contextmanager
def _http_errors():
    try:
        yield
    except AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


def _set_session(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.python_env == "production",
        path="/",
    )


def _visible(service: AuthService, user: User) -> List[VisibleAccount]:
    return [
        VisibleAccount(
            id=account.id,
            client_id=account.client_id,
            name=display_name(account),
            number_last4=last_four(account),
            shared=shared,
        )
        for account, shared in service.accessible_accounts(user)
    ]


def _me(service: AuthService, user: User) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        client_id=user.client_id,
        accounts=_visible(service, user),
    )


def _link(token: str, record: AuthToken) -> LinkResponse:
    route = "invite" if record.purpose == PURPOSE_INVITE else "reset"
    return LinkResponse(
        token=token,
        path=f"/{route}/{token}",
        purpose=record.purpose,
        email=record.user.email,
        expires_at=record.expires_at,
    )


@router.post("/login", response_model=MeResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Sign in. The session is set as an http-only cookie."""
    service = AuthService(db)
    with _http_errors():
        user, token = service.login(body.email, body.password)
    _set_session(response, token)
    return _me(service, user)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
):
    AuthService(db).logout(session_token)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The signed-in user and, for a client, the accounts they may view."""
    return _me(AuthService(db), user)


@router.post("/password", response_model=MeResponse)
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change your own password. Every other session of yours is ended."""
    service = AuthService(db)
    with _http_errors():
        token = service.change_password(user, body.current_password, body.new_password)
    _set_session(response, token)
    return _me(service, user)


@router.get("/users", response_model=List[UserResponse])
def list_users(_: User = Depends(require_advisor), db: Session = Depends(get_db)):
    return [
        UserResponse(
            id=u.id,
            email=u.email,
            name=u.name,
            role=u.role,
            client_id=u.client_id,
            is_active=u.is_active,
            has_password=bool(u.password_hash),
            last_login_at=u.last_login_at,
        )
        for u in AuthService(db).users()
    ]


@router.post("/invites", response_model=LinkResponse, status_code=201)
def invite_client(
    body: InviteRequest,
    _: User = Depends(require_advisor),
    db: Session = Depends(get_db),
):
    """Create a client's login and a one-time link for them to set a password."""
    with _http_errors():
        token, record = AuthService(db).invite_client(body.client_id)
    return _link(token, record)


@router.post("/users/{user_id}/password-reset", response_model=LinkResponse)
def password_reset_link(
    user_id: str,
    _: User = Depends(require_advisor),
    db: Session = Depends(get_db),
):
    """A one-time link for a user to choose a new password."""
    with _http_errors():
        token, record = AuthService(db).reset_link(user_id)
    return _link(token, record)


@router.get("/links/{token}", response_model=LinkPreview)
def preview_link(token: str, db: Session = Depends(get_db)):
    """Who an invite or reset link is for, shown before a password is chosen."""
    service = AuthService(db)
    with _http_errors():
        record, user = service.link_user(token)
    return LinkPreview(
        purpose=record.purpose,
        email=user.email,
        name=user.name,
        accounts=_visible(service, user),
    )


@router.post("/links/{token}/accept", response_model=MeResponse)
def accept_link(
    token: str,
    body: PasswordRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Set the password an invite or reset link was issued for, and sign in."""
    service = AuthService(db)
    with _http_errors():
        user, session_token = service.accept_link(token, body.password)
    _set_session(response, session_token)
    return _me(service, user)


def _access_response(access: AccountAccess) -> AccountAccessResponse:
    return AccountAccessResponse(
        client_id=access.client_id,
        account_id=access.account_id,
        account_name=display_name(access.account),
        owner_client_id=access.account.client_id,
        owner_name=access.account.client.name,
    )


@access_router.get(
    "/clients/{client_id}/account-access", response_model=List[AccountAccessResponse]
)
def list_account_access(client_id: str, db: Session = Depends(get_db)):
    """Other clients' accounts this client has been allowed to view."""
    return [_access_response(a) for a in AuthService(db).grants(client_id)]


@access_router.post(
    "/clients/{client_id}/account-access",
    response_model=AccountAccessResponse,
    status_code=201,
)
def grant_account_access(
    client_id: str, body: AccountAccessRequest, db: Session = Depends(get_db)
):
    """Let this client view an account that belongs to another client."""
    with _http_errors():
        return _access_response(AuthService(db).grant(client_id, body.account_id))


@access_router.delete(
    "/clients/{client_id}/account-access/{account_id}", status_code=204
)
def revoke_account_access(
    client_id: str, account_id: str, db: Session = Depends(get_db)
):
    if not AuthService(db).revoke(client_id, account_id):
        raise HTTPException(status_code=404, detail="No such access")
