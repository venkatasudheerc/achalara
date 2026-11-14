"""Client endpoints"""
from contextlib import contextmanager
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional

from app.db.database import get_db
from app.models.client import Client
from app.models.account import Account
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.models.user import User
from app.api.deps import get_current_user
from app.api.schemas.client import (
    ClientCreate,
    ClientResponse,
    ClientUpdate,
    GuardianRequest,
    Relative,
    RelativeCreate,
    SpouseRequest,
)
from app.models.user import ROLE_ADMIN, ROLE_ADVISOR
from app.services.auth_service import AuthError, AuthService
from app.api.schemas.performance import (
    LevelPerformance,
    MonthlyReturnsResponse,
    MonthlyReturn,
)
from app.services.performance_service import PerformanceService

router = APIRouter()


def _advisor_or_422(db: Session, advisor_id: Optional[str]) -> Optional[str]:
    if advisor_id is None:
        return None
    advisor = db.get(User, advisor_id)
    if advisor is None or advisor.role != ROLE_ADVISOR:
        raise HTTPException(status_code=422, detail="No such advisor")
    return advisor.id


@router.post("/", response_model=ClientResponse, status_code=201)
def create_client(
    client: ClientCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new client. An advisor's new client is theirs; an admin may
    assign one to an advisor."""
    if client.email and db.query(Client).filter(Client.email == client.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    advisor_id = user.id if user.role == ROLE_ADVISOR else _advisor_or_422(db, client.advisor_id)

    db_client = Client(name=client.name, email=client.email, advisor_id=advisor_id)
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client


@router.get("/", response_model=list[ClientResponse])
def list_clients(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The clients the signed-in admin or advisor manages, oldest first: every
    client for an admin, their own for an advisor."""
    query = db.query(Client).order_by(Client.created_at)
    if user.role != ROLE_ADMIN:
        query = query.filter(Client.advisor_id == user.id)
    return query.offset(skip).limit(limit).all()


@router.get("/{client_id}", response_model=ClientResponse)
def get_client(client_id: str, db: Session = Depends(get_db)):
    """Get client by ID"""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.patch("/{client_id}", response_model=ClientResponse)
def update_client(
    client_id: str,
    body: ClientUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Correct a client's name or contact email; an admin may also assign or
    unassign their advisor.

    A new name is carried to the client's login, which is where the portal
    reads it. The sign-in email is not touched.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if body.email is not None and body.email != client.email:
        taken = (
            db.query(Client)
            .filter(Client.email == body.email, Client.id != client_id)
            .first()
        )
        if taken:
            raise HTTPException(status_code=400, detail="Email already registered")
        client.email = body.email
    if "advisor_id" in body.model_fields_set:
        if user.role != ROLE_ADMIN:
            raise HTTPException(status_code=403, detail="Only an admin assigns advisors")
        client.advisor_id = _advisor_or_422(db, body.advisor_id)
    if body.name is not None and body.name.strip() != client.name:
        if not body.name.strip():
            raise HTTPException(status_code=422, detail="A name is needed")
        client.name = body.name.strip()
        db.query(User).filter(User.client_id == client_id).update(
            {User.name: client.name}
        )
    db.commit()
    db.refresh(client)
    return client


@contextmanager
def _relation_errors():
    try:
        yield
    except AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


def _managed_or_404(db: Session, user: User, client_id: Optional[str]) -> None:
    if client_id and not AuthService(db).manages(user, client_id):
        raise HTTPException(status_code=404, detail="Client not found")


@router.put("/{client_id}/spouse", response_model=ClientResponse)
def set_spouse(
    client_id: str,
    body: SpouseRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Make two clients each other's spouse (they then see each other's
    accounts, but not private ones), or end it with null."""
    _managed_or_404(db, user, body.spouse_id)
    with _relation_errors():
        return AuthService(db).set_spouse(client_id, body.spouse_id)


@router.put("/{client_id}/guardian", response_model=ClientResponse)
def set_guardian(
    client_id: str,
    body: GuardianRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a client a minor in another client's care (the guardian and the
    guardian's spouse then see the minor's accounts), or not a minor with null."""
    _managed_or_404(db, user, body.guardian_id)
    with _relation_errors():
        return AuthService(db).set_guardian(client_id, body.guardian_id)


@router.get("/{client_id}/relatives", response_model=list[Relative])
def list_relatives(client_id: str, db: Session = Depends(get_db)):
    """The client's spouse and minors."""
    with _relation_errors():
        return _relatives(db, client_id)


@router.post("/{client_id}/relatives", response_model=ClientResponse, status_code=201)
def add_relative(client_id: str, body: RelativeCreate, db: Session = Depends(get_db)):
    """Add the client's spouse or a minor as a new client, with the same advisor."""
    with _relation_errors():
        return AuthService(db).add_relative(client_id, body.name, body.relation, body.email)


def _relatives(db: Session, client_id: str) -> list:
    with_login = {
        row[0] for row in db.query(User.client_id).filter(User.client_id.isnot(None))
    }
    return [
        Relative(id=c.id, name=c.name, email=c.email, relation=relation, has_login=c.id in with_login)
        for c, relation in AuthService(db).relatives(client_id)
    ]


@router.get("/{client_id}/performance", response_model=LevelPerformance)
def get_client_performance(
    client_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Client-level roll-up of MWR/TWR computed on the merged cash-flow stream
    across every sleeve in the client, plus per-account children."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be before end_date"
        )
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    svc = PerformanceService(db)
    all_sleeve_ids = svc.sleeve_ids_for_client(client_id)

    perf = svc.performance(
        all_sleeve_ids,
        start_date,
        end_date,
        cash_account_ids=svc.account_ids_for_client(client_id),
    )

    accounts = db.query(Account).filter(Account.client_id == client_id).all()
    children = []
    for account in accounts:
        acct_sleeve_ids = svc.sleeve_ids_for_account(account.id)
        child = svc.performance(
            acct_sleeve_ids, start_date, end_date, cash_account_ids=[account.id]
        )
        children.append(
            {
                "level": "account",
                "id": account.id,
                "name": account.name,
                "summary": child["summary"],
            }
        )

    return {
        "level": "client",
        "id": client_id,
        "name": client.name,
        "start_date": perf.get("start_date"),
        "end_date": perf.get("end_date"),
        "summary": perf["summary"],
        "timeseries": perf["timeseries"],
        "children": children,
    }


@router.get("/{client_id}/performance/returns-series")
def get_client_returns_series(
    client_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    basis: str = Query(
        "market",
        pattern="^(market|realized)$",
        description="market: holdings at each day's prices. realized: at cost, "
        "so unrealised gains are left out",
    ),
    db: Session = Depends(get_db),
):
    """Weekly TWR + MWR timeseries for a client (aggregated from sleeve snapshots)."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    from app.services.weekly_snapshot_service import WeeklySnapshotService

    svc = PerformanceService(db)
    sleeve_ids = svc.sleeve_ids_for_client(client_id)
    series = WeeklySnapshotService(db).returns_series(
        sleeve_ids,
        start_date,
        end_date,
        cash_account_ids=svc.account_ids_for_client(client_id),
        basis=basis,
    )
    return {"level": "client", "id": client_id, "series": series}


@router.get("/{client_id}/performance/monthly", response_model=MonthlyReturnsResponse)
def get_client_monthly_returns(
    client_id: str,
    basis: str = Query(
        "market",
        pattern="^(market|realized)$",
        description="market: holdings at each day's prices. realized: at cost, "
        "so unrealised gains are left out",
    ),
    db: Session = Depends(get_db),
):
    """Month-on-month return breakdown since inception for a client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    svc = PerformanceService(db)
    sleeve_ids = svc.sleeve_ids_for_client(client_id)
    months = svc.monthly_returns(
        sleeve_ids, cash_account_ids=svc.account_ids_for_client(client_id), basis=basis
    )
    cumulative = None
    non_none = [m["return_pct"] for m in months if m["return_pct"] is not None]
    if non_none:
        product = 1.0
        for r in non_none:
            product *= 1 + r / 100
        cumulative = round((product - 1) * 100, 2)
    return MonthlyReturnsResponse(
        months=[MonthlyReturn(**m) for m in months],
        cumulative_return_pct=cumulative,
    )


@router.get("/{client_id}/positions")
def get_client_positions(client_id: str, db: Session = Depends(get_db)):
    """Get all positions merged across all sleeves for a client"""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    svc = PerformanceService(db)
    sleeve_ids = svc.sleeve_ids_for_client(client_id)
    payload = svc.positions_payload(sleeve_ids)
    return {"client_id": client_id, **payload}


@router.get("/{client_id}/trades")
def get_client_trades(
    client_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Get all trades across all sleeves for a client, with pagination"""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    base_query = (
        db.query(Trade)
        .join(Sleeve, Trade.sleeve_id == Sleeve.id)
        .join(Account, Sleeve.account_id == Account.id)
        .filter(Account.client_id == client_id)
    )
    total = base_query.count()
    trades = (
        base_query.order_by(Trade.trade_date.desc()).offset(skip).limit(limit).all()
    )

    return {
        "client_id": client_id,
        "total": total,
        "skip": skip,
        "limit": limit,
        "trades": [
            {
                "id": t.id,
                "sleeve_id": t.sleeve_id,
                "trade_date": t.trade_date,
                "symbol": t.symbol,
                "action": t.action,
                "quantity": float(t.quantity),
                "price": float(t.price),
                "commission": float(t.commission),
                "notes": t.notes,
                "security_type": t.security_type,
            }
            for t in trades
        ],
    }
