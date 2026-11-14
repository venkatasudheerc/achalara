"""The client portal: one client's accounts, read together.

Every route answers for the signed-in client (or, for an advisor, the client
named in ``as_client``). Nothing here takes a client id in its path, so the
viewer cannot ask for anyone else's data.
"""
import csv
import io
from contextlib import contextmanager
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import PortalViewer, portal_viewer
from app.api.schemas.portal import (
    AccountGroupCreate,
    AccountGroupMembers,
    AccountGroupResponse,
    AccountGroupsResponse,
    AccountGroupUpdate,
    PortalAccountsResponse,
    PortalActivityResponse,
    PortalHomeResponse,
    PortalOverviewResponse,
    PortalPerformanceResponse,
    PortalPositionsResponse,
    PortalRealizedResponse,
    PortalTradesResponse,
)
from app.api.schemas.imports import ImportPreview, ImportResult
from app.db.database import get_db
from app.models.account import Account
from app.services.account_import_service import (
    MAX_FILE_BYTES,
    AccountImportError,
    AccountImportService,
)
from app.services.account_group_service import AccountGroupService
from app.services.performance_stats_service import GRAINS
from app.services.portal_service import PortalError, PortalService

router = APIRouter()

_ACCOUNT = Query(None, description="Limit to one account in view")
_ACCOUNTS = Query(
    None, description="Limit to these accounts in view (repeat the parameter for each)"
)
_STRATEGY = Query(None, description="Limit to one strategy")
_TYPE = Query(None, pattern="^(stock|etf|option|other)$", alias="type")
_SYMBOL = Query(None, alias="q", max_length=50, description="Symbol contains")
_FORMAT = Query("json", pattern="^(json|csv)$", alias="format")
_CSV_ROW_LIMIT = 10000


@contextmanager
def _http_errors():
    try:
        yield
    except PortalError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


def _service(
    viewer: PortalViewer, db: Session, account_ids: Optional[List[str]] = None
) -> PortalService:
    """The viewer's portal, narrowed to ``account_ids`` when some are named."""
    return PortalService(db, viewer.client_id).narrow(account_ids)


def _csv(
    filename: str, columns: Sequence[Tuple[str, str]], rows: List[Dict]
) -> Response:
    """``rows`` as a CSV download with ``columns`` given as (header, key)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([header for header, _ in columns])
    for row in rows:
        writer.writerow(
            ["" if row.get(key) is None else row[key] for _, key in columns]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


_PLACE = (("Account", "account_name"), ("Strategy", "strategy_name"))


@router.get("/accounts", response_model=PortalAccountsResponse)
def portal_accounts(
    viewer: PortalViewer = Depends(portal_viewer), db: Session = Depends(get_db)
):
    """Whose portal this is, the accounts in view, and each one's strategies."""
    return {
        "viewer": {
            "client_id": viewer.client_id,
            "name": viewer.name,
            "preview": viewer.preview,
        },
        "accounts": _service(viewer, db).accounts(),
    }


def _groups(
    viewer: PortalViewer, db: Session, change: bool = False
) -> AccountGroupService:
    """The viewer's groups. An advisor previewing a client may look but not change."""
    if change and viewer.preview:
        raise HTTPException(
            status_code=403, detail="Only the client can change their groups"
        )
    return AccountGroupService(db, viewer.client_id)


@router.get("/groups", response_model=AccountGroupsResponse)
def portal_groups(
    viewer: PortalViewer = Depends(portal_viewer), db: Session = Depends(get_db)
):
    """The client's own named groups of accounts, in their chosen order."""
    return {"groups": _groups(viewer, db).list()}


@router.post("/groups", response_model=AccountGroupResponse, status_code=201)
def portal_create_group(
    body: AccountGroupCreate,
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """A new group, optionally with its accounts. Names are unique per client."""
    with _http_errors():
        return _groups(viewer, db, change=True).create(body.name, body.account_ids)


@router.patch("/groups/{group_id}", response_model=AccountGroupResponse)
def portal_update_group(
    group_id: str,
    body: AccountGroupUpdate,
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """Rename a group or move it in the list."""
    with _http_errors():
        return _groups(viewer, db, change=True).update(
            group_id, body.name, body.position
        )


@router.put("/groups/{group_id}/accounts", response_model=AccountGroupResponse)
def portal_set_group_accounts(
    group_id: str,
    body: AccountGroupMembers,
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """Replace the group's accounts. Each must be an account the client can see."""
    with _http_errors():
        return _groups(viewer, db, change=True).set_accounts(group_id, body.account_ids)


@router.delete("/groups/{group_id}", status_code=204)
def portal_delete_group(
    group_id: str,
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """Remove a group. Its accounts are not touched."""
    with _http_errors():
        _groups(viewer, db, change=True).delete(group_id)
    return Response(status_code=204)


@router.get("/home", response_model=PortalHomeResponse)
def portal_home(
    account_id: Optional[str] = _ACCOUNT,
    account_ids: Optional[List[str]] = _ACCOUNTS,
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """The home page: value and the day's change at live prices, this year's
    return against the benchmark, where the money is, the largest holdings,
    and what is worth knowing (options about to expire, losses still carried,
    holdings about to become long-term, a holding that dominates)."""
    with _http_errors():
        return _service(viewer, db, account_ids).home(account_id)


@router.get("/overview", response_model=PortalOverviewResponse)
def portal_overview(
    account_id: Optional[str] = _ACCOUNT,
    account_ids: Optional[List[str]] = _ACCOUNTS,
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """Home: value, this year's return and gain, each account by strategy,
    the value over time, and recent activity."""
    with _http_errors():
        return _service(viewer, db, account_ids).overview(account_id)


@router.get("/positions", response_model=PortalPositionsResponse)
def portal_positions(
    account_id: Optional[str] = _ACCOUNT,
    account_ids: Optional[List[str]] = _ACCOUNTS,
    strategy_id: Optional[str] = _STRATEGY,
    security_type: Optional[str] = _TYPE,
    query: Optional[str] = _SYMBOL,
    live: bool = Query(
        True,
        description="Show holdings at the market's current price where one can "
        "be had. False shows the custodian's last reported prices.",
    ),
    output: str = _FORMAT,
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """Open positions, one row per holding per strategy.

    What is held and what it cost are the custodian's. Prices are the market's
    current ones unless ``live`` is false; a holding with no live quote keeps
    the custodian's price.
    """
    with _http_errors():
        result = _service(viewer, db, account_ids).positions(
            account_id, strategy_id, security_type, query, live
        )
    if output == "csv":
        return _csv(
            "positions.csv",
            (
                ("Symbol", "symbol"),
                *_PLACE,
                ("Type", "security_type"),
                ("Quantity", "quantity"),
                ("Average cost per share", "avg_cost"),
                ("Shares per unit", "multiplier"),
                ("Price", "price"),
                ("Price from", "price_source"),
                ("Cost", "cost_basis"),
                ("Market value", "market_value"),
                ("Unrealised gain", "unrealized_gain"),
            ),
            result["positions"],
        )
    return result


@router.get("/trades", response_model=PortalTradesResponse)
def portal_trades(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    account_id: Optional[str] = _ACCOUNT,
    account_ids: Optional[List[str]] = _ACCOUNTS,
    strategy_id: Optional[str] = _STRATEGY,
    action: Optional[str] = Query(None, pattern="^(?i:buy|sell)$"),
    security_type: Optional[str] = _TYPE,
    query: Optional[str] = _SYMBOL,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    output: str = _FORMAT,
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """Trades, newest first, with totals for everything the filters match."""
    as_csv = output == "csv"
    with _http_errors():
        result = _service(viewer, db, account_ids).trades(
            start_date,
            end_date,
            account_id,
            strategy_id,
            action,
            security_type,
            query,
            0 if as_csv else skip,
            _CSV_ROW_LIMIT if as_csv else limit,
        )
    if as_csv:
        return _csv(
            "trades.csv",
            (
                ("Date", "trade_date"),
                ("Symbol", "symbol"),
                ("Action", "action"),
                ("Option ended", "event"),
                ("Type", "security_type"),
                ("Quantity", "quantity"),
                ("Shares per unit", "multiplier"),
                ("Price per share", "price"),
                ("Amount", "amount"),
                ("Commission", "commission"),
                *_PLACE,
            ),
            result["trades"],
        )
    return result


@router.get("/activity", response_model=PortalActivityResponse)
def portal_activity(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    account_id: Optional[str] = _ACCOUNT,
    account_ids: Optional[List[str]] = _ACCOUNTS,
    strategy_id: Optional[str] = _STRATEGY,
    show: str = Query("all", pattern="^(all|trades|money|income|charges)$"),
    action: Optional[str] = Query(None, pattern="^(?i:buy|sell)$"),
    security_type: Optional[str] = _TYPE,
    query: Optional[str] = _SYMBOL,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    output: str = _FORMAT,
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """Trades and the cash that moved (deposits, withdrawals, transfers,
    dividends, interest, charges), newest first, with totals for everything
    the filters match."""
    as_csv = output == "csv"
    with _http_errors():
        result = _service(viewer, db, account_ids).activity(
            start_date,
            end_date,
            account_id,
            strategy_id,
            show,
            action,
            security_type,
            query,
            0 if as_csv else skip,
            _CSV_ROW_LIMIT if as_csv else limit,
        )
    if as_csv:
        return _csv(
            "activity.csv",
            (
                ("Date", "date"),
                ("Activity", "label"),
                ("Symbol", "symbol"),
                ("Detail", "detail"),
                ("Quantity", "quantity"),
                ("Shares per unit", "multiplier"),
                ("Price per share", "price"),
                ("Amount", "amount"),
                *_PLACE,
            ),
            result["rows"],
        )
    return result


@router.get("/realized", response_model=PortalRealizedResponse)
def portal_realized(
    start_date: Optional[date] = Query(None, description="Closed on or after"),
    end_date: Optional[date] = Query(None, description="Closed on or before"),
    account_id: Optional[str] = _ACCOUNT,
    account_ids: Optional[List[str]] = _ACCOUNTS,
    strategy_id: Optional[str] = _STRATEGY,
    term: Optional[str] = Query(None, pattern="^(short|long)$"),
    security_type: Optional[str] = _TYPE,
    result: Optional[str] = Query(None, pattern="^(gain|loss)$"),
    query: Optional[str] = _SYMBOL,
    grain: str = Query(
        "month", pattern="^(month|quarter)$", description="How `periods` is cut"
    ),
    output: str = _FORMAT,
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """Closed positions and their realised gains, newest first."""
    with _http_errors():
        payload = _service(viewer, db, account_ids).realized(
            start_date,
            end_date,
            account_id,
            strategy_id,
            term,
            security_type,
            result,
            query,
            grain,
        )
    if output == "csv":
        return _csv(
            "realised-gains.csv",
            (
                ("Symbol", "symbol"),
                ("Type", "security_type"),
                ("Option ended", "event"),
                ("Opened", "opened_at"),
                ("Closed", "closed_at"),
                ("Days held", "days_held"),
                ("Quantity", "quantity"),
                ("Shares per unit", "multiplier"),
                ("Entry price per share", "entry_price"),
                ("Exit price per share", "exit_price"),
                ("Cost", "cost"),
                ("Proceeds", "proceeds"),
                ("Short-term gain / loss", "short_term_gain"),
                ("Long-term gain / loss", "long_term_gain"),
                ("Wash sale loss disallowed", "disallowed_loss"),
                ("Gain / loss", "realized_gain"),
                *_PLACE,
            ),
            payload["positions"],
        )
    return payload


@router.get("/performance", response_model=PortalPerformanceResponse)
def portal_performance(
    account_id: Optional[str] = _ACCOUNT,
    account_ids: Optional[List[str]] = _ACCOUNTS,
    strategy_id: Optional[str] = _STRATEGY,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    grain: str = Query("month", description="day | week | month | quarter | year"),
    benchmark: Optional[str] = Query(
        None, description="A code from the response's `benchmarks`; SPX when left out"
    ),
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """Returns for a window: a summary, the cumulative lines against the
    chosen benchmark, every month of the record, and rows by period."""
    if grain not in GRAINS:
        raise HTTPException(
            status_code=422, detail=f"grain must be one of {', '.join(GRAINS)}"
        )
    with _http_errors():
        payload = _service(viewer, db, account_ids).performance(
            account_id, strategy_id, start_date, end_date, grain, benchmark
        )
    return {**payload, "grain": grain}


# ----------------------------------------------------------------------
# Upload and import: a client adds a custodian's file to an account they own
# ----------------------------------------------------------------------


def _own_account(viewer: PortalViewer, db: Session, account_id: str) -> Account:
    """An account the viewer owns. Shared accounts are read-only, and an advisor
    previewing a client imports from the client's page instead."""
    if viewer.preview:
        raise HTTPException(
            status_code=403, detail="Import from the client's page, not the preview"
        )
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.client_id == viewer.client_id)
        .first()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _import(viewer, db, account_id: str, file: UploadFile, write: bool):
    account = _own_account(viewer, db, account_id)
    content = file.file.read(MAX_FILE_BYTES + 1)
    service = AccountImportService(db)
    try:
        if write:
            return service.apply(account, file.filename or "", content)
        return service.preview(account, file.filename or "", content)
    except AccountImportError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


@router.post("/accounts/{account_id}/imports/preview", response_model=ImportPreview)
def portal_import_preview(
    account_id: str,
    file: UploadFile = File(..., description="The custodian's activity report or Achalara's template"),
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """What the file would add to one of the client's own accounts. Nothing is written."""
    return _import(viewer, db, account_id, file, write=False)


@router.post("/accounts/{account_id}/imports", response_model=ImportResult)
def portal_import(
    account_id: str,
    file: UploadFile = File(..., description="The same file as the preview"),
    viewer: PortalViewer = Depends(portal_viewer),
    db: Session = Depends(get_db),
):
    """Add what the file holds that is not on file to one of the client's own
    accounts, rebuild its history and check its holdings."""
    return _import(viewer, db, account_id, file, write=True)
