"""Request dependencies: who is signed in, and whether they may make this call."""
from dataclasses import dataclass
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.client import Client
from app.models.user import ROLE_ADMIN, ROLE_ADVISOR, User
from app.services.auth_service import SESSION_COOKIE, AuthService

# Read routes under /clients/{client_id} that a client user may not read.
_STAFF_ONLY_SUFFIXES = ("/account-access",)
# Routes outside any one client that an advisor may use: the client list (which
# answers with their own clients only) and the strategies' definitions.
_ADVISOR_ROUTES = {
    ("GET", "/api/v1/clients/"),
    ("POST", "/api/v1/clients/"),
    ("GET", "/api/v1/strategies/"),
    ("GET", "/api/v1/strategies/{strategy_id}"),
    # The routes check the sleeve belongs to a client the advisor manages.
    ("POST", "/api/v1/trades/"),
    ("POST", "/api/v1/trades/reassign"),
}
# Routes outside any client that every signed-in user may read.
_SHARED_READ_PREFIXES = ("/api/v1/benchmarks", "/api/v1/research")


def get_current_user(
    session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> User:
    user = AuthService(db).user_for_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """The platform's super user only."""
    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Not allowed")
    return user


def require_staff(user: User = Depends(get_current_user)) -> User:
    """An admin or an advisor; the route checks the advisor manages the client."""
    if user.role not in (ROLE_ADMIN, ROLE_ADVISOR):
        raise HTTPException(status_code=403, detail="Not allowed")
    return user


def require_access(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """The rule for every data route, applied where the router is mounted.

    An admin may call anything. An advisor may call anything under a client
    assigned to them, the client list and the strategies' definitions, and read
    the shared reference data. A client user may only read, and only: their own
    client's roll-ups; an account the guardrails let them see
    (``AuthService.accounts_for_client``) and everything beneath it; and the
    shared reference data.
    """
    if user.role == ROLE_ADMIN:
        return user

    route_path = getattr(request.scope.get("route"), "path", "")
    client_id = request.path_params.get("client_id")
    account_id = request.path_params.get("account_id")

    if user.role == ROLE_ADVISOR:
        if client_id:
            allowed = AuthService(db).manages(user, client_id)
            if allowed and account_id:
                allowed = AuthService(db).can_read_account(user, client_id, account_id)
        else:
            allowed = (request.method, route_path) in _ADVISOR_ROUTES or (
                request.method == "GET" and route_path.startswith(_SHARED_READ_PREFIXES)
            )
        if not allowed:
            raise HTTPException(status_code=403, detail="Not allowed")
        return user

    allowed = False
    if request.method == "GET" and not route_path.endswith(_STAFF_ONLY_SUFFIXES):
        if client_id and account_id:
            allowed = AuthService(db).can_read_account(user, client_id, account_id)
        elif client_id:
            allowed = client_id == user.client_id
        else:
            allowed = route_path.startswith(_SHARED_READ_PREFIXES)
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed")
    return user


@dataclass
class PortalViewer:
    """Whose portal a request is for."""

    client_id: str
    name: str
    preview: bool  # an admin or advisor looking at a client's portal


def portal_viewer(
    as_client: Optional[str] = Query(
        None, description="Admin only: the client whose portal to preview"
    ),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortalViewer:
    """The portal shows a client user their own data. An admin may open any
    client's portal by naming the client, an advisor one of their own clients';
    a client user cannot name another."""
    if user.role not in (ROLE_ADMIN, ROLE_ADVISOR):
        return PortalViewer(client_id=user.client_id, name=user.name, preview=False)
    if not as_client:
        raise HTTPException(status_code=422, detail="Name a client to preview")
    client = db.query(Client).filter(Client.id == as_client).first()
    if client is None or not AuthService(db).manages(user, client.id):
        raise HTTPException(status_code=404, detail="Client not found")
    return PortalViewer(client_id=client.id, name=client.name, preview=True)
