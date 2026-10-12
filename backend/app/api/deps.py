"""Request dependencies: who is signed in, and whether they may make this call."""
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.user import ROLE_ADVISOR, User
from app.services.auth_service import SESSION_COOKIE, AuthService

# Read routes under /clients/{client_id} that stay with the advisor.
_ADVISOR_ONLY_SUFFIXES = ("/connections", "/account-access")
# Routes outside any client that every signed-in user may read.
_SHARED_READ_PREFIXES = ("/api/v1/benchmarks",)


def get_current_user(
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> User:
    user = AuthService(db).user_for_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return user


def require_advisor(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_ADVISOR:
        raise HTTPException(status_code=403, detail="Not allowed")
    return user


def require_access(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """The rule for every data route, applied where the router is mounted.

    An advisor may call anything. A client user may only read, and only:
    their own client's roll-ups; an account they own or have been granted
    (and everything beneath it); and the shared reference data.
    """
    if user.role == ROLE_ADVISOR:
        return user

    route_path = getattr(request.scope.get("route"), "path", "")
    client_id = request.path_params.get("client_id")
    account_id = request.path_params.get("account_id")

    allowed = False
    if request.method == "GET" and not route_path.endswith(_ADVISOR_ONLY_SUFFIXES):
        if client_id and account_id:
            allowed = AuthService(db).can_read_account(user, client_id, account_id)
        elif client_id:
            allowed = client_id == user.client_id
        else:
            allowed = route_path.startswith(_SHARED_READ_PREFIXES)
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed")
    return user
