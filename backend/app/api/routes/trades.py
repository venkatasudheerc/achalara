"""Trade endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.account import Account
from app.models.user import User
from app.services.auth_service import AuthService
from app.models.trade import Trade
from app.models.sleeve import Sleeve
from app.api.schemas.trade import TradeCreate, TradeResponse
from app.api.schemas.connection import ReassignRequest, ReassignResult
from app.services.trade_reassignment import reassign_symbols
from app.services.performance_build_service import rebuild_for_sleeves

router = APIRouter()


def _managed_sleeve_or_404(db: Session, user: User, sleeve_id: str) -> Sleeve:
    """The sleeve, if it belongs to a client the admin or advisor manages."""
    sleeve = db.query(Sleeve).filter(Sleeve.id == sleeve_id).first()
    account = db.get(Account, sleeve.account_id) if sleeve else None
    if account is None or not AuthService(db).manages(user, account.client_id):
        raise HTTPException(status_code=404, detail="Sleeve not found")
    return sleeve


@router.post("/", response_model=TradeResponse, status_code=201)
def create_trade(
    trade: TradeCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new trade, in a client the admin or advisor manages."""
    sleeve = _managed_sleeve_or_404(db, user, trade.sleeve_id)
    if not sleeve:
        raise HTTPException(status_code=404, detail="Sleeve not found")

    db_trade = Trade(
        sleeve_id=trade.sleeve_id,
        trade_date=trade.trade_date,
        symbol=trade.symbol,
        action=trade.action,
        quantity=trade.quantity,
        price=trade.price,
        commission=trade.commission,
        notes=trade.notes,
    )
    db.add(db_trade)
    db.commit()
    db.refresh(db_trade)

    rebuild_for_sleeves(db, [trade.sleeve_id])

    return db_trade


@router.post("/reassign", response_model=ReassignResult)
def reassign_trades(
    body: ReassignRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Move every trade of the named symbols to another sleeve of the account."""
    _managed_sleeve_or_404(db, user, body.from_sleeve_id)
    _managed_sleeve_or_404(db, user, body.to_sleeve_id)
    try:
        return reassign_symbols(
            db, body.from_sleeve_id, body.to_sleeve_id, body.symbols
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
