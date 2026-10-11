"""Trade endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.trade import Trade
from app.models.sleeve import Sleeve
from app.api.schemas.trade import TradeCreate, TradeResponse
from app.api.schemas.connection import ReassignRequest, ReassignResult
from app.services.trade_reassignment import reassign_symbols
from app.services.performance_build_service import rebuild_for_sleeves

router = APIRouter()


@router.post("/", response_model=TradeResponse, status_code=201)
def create_trade(trade: TradeCreate, db: Session = Depends(get_db)):
    """Create a new trade"""
    sleeve = db.query(Sleeve).filter(Sleeve.id == trade.sleeve_id).first()
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
def reassign_trades(body: ReassignRequest, db: Session = Depends(get_db)):
    """Move every trade of the named symbols to another sleeve of the account."""
    try:
        return reassign_symbols(
            db, body.from_sleeve_id, body.to_sleeve_id, body.symbols
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
