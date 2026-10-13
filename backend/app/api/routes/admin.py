"""Admin endpoints for imports and sync"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
import logging
import uuid

from app.api.schemas.status import AlertTestResponse, SystemStatusResponse
from app.connectors.models import NotSupported
from app.db.database import get_db
from app.services import alerts
from app.services.connection_service import ConnectionService
from app.services.status_service import StatusService
from app.services.performance_build_service import (
    PerformanceBuildService,
    rebuild_for_sleeves,
)
from app.services.trade_import import TradeImportService
from app.services.daily_sync import run_daily_sync
from app.models.account import Account
from app.models.sleeve import Sleeve
from app.models.sync_log import SyncLog
from app.models.sheet_sync_config import SheetSyncConfig

router = APIRouter()


@router.get("/status", response_model=SystemStatusResponse)
def system_status(db: Session = Depends(get_db)):
    """Whether everything is running as it should: the daily jobs, brokerage
    accounts, data freshness, the last backup and recent warnings."""
    return StatusService(db).status()


@router.post("/status/test-alert", response_model=AlertTestResponse)
def send_test_alert():
    """Send a test message through the configured alert channel."""
    if not alerts.configured():
        raise HTTPException(
            status_code=503, detail="No alert channel is configured on the server."
        )
    return {"sent": alerts.send("Achalara: this is a test alert. Alerts are working.")}


@router.post("/status/check-links", response_model=SystemStatusResponse)
def check_brokerage_links(db: Session = Depends(get_db)):
    """Ask the source now whether each brokerage link is still sharing data,
    then return the status afresh."""
    try:
        ConnectionService(db).check_links()
    except NotSupported as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        logger.exception("Brokerage link check failed")
        raise HTTPException(
            status_code=502, detail="The brokerage source did not answer."
        )
    alerts.run_status_watch(db)
    return StatusService(db).status()


logger = logging.getLogger(__name__)


def _sleeve_for_client(db: Session, sleeve_id: str, client_id: str) -> Sleeve | None:
    """Return the sleeve only if it belongs to an account owned by the client."""
    return (
        db.query(Sleeve)
        .join(Account, Sleeve.account_id == Account.id)
        .filter(Sleeve.id == sleeve_id, Account.client_id == client_id)
        .first()
    )


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------


@router.post("/import-historical")
def import_historical(
    client_id: str = Query(..., description="Client ID"),
    sleeve_id: str = Query(
        None,
        description="Optional. If set, import all rows into this sleeve. "
        "If omitted, auto-route each row by its Account + Strategy columns.",
    ),
    mode: str = Query("VALIDATE", description="VALIDATE or IMPORT"),
    file: UploadFile = File(..., description="CSV file with trades"),
    db: Session = Depends(get_db),
):
    """
    Import historical trades from a CSV file.

    CSV columns: Date, Symbol, Action, Quantity, Price, Commission, Strategy, Account, Notes

    Two routing modes:
    - **Single sleeve** (pass ``sleeve_id``): every row imports into that sleeve;
      the Account/Strategy columns are ignored.
    - **Auto-route** (omit ``sleeve_id``): each row is routed to the Account
      (by account number) + global Strategy (by name) named in the row, creating the
      account, strategy and/or sleeve if missing. Supports files spanning multiple
      accounts/strategies.

    Operation modes:
    - VALIDATE: validate only, write nothing (reports what *would* be created/imported)
    - IMPORT: validate and persist, with per-sleeve deduplication
    """
    if mode not in ["VALIDATE", "IMPORT"]:
        raise HTTPException(
            status_code=400, detail="Mode must be 'VALIDATE' or 'IMPORT'"
        )

    import_service = TradeImportService(db)
    file_content = file.file.read()

    try:
        if sleeve_id:
            sleeve = _sleeve_for_client(db, sleeve_id, client_id)
            if not sleeve:
                raise HTTPException(
                    status_code=404,
                    detail=f"Sleeve {sleeve_id} not found for client {client_id}",
                )
            result = import_service.import_from_file(file_content, sleeve_id, mode=mode)
        else:
            result = import_service.import_routed(file_content, client_id, mode=mode)

        if not result["success"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Import validation failed",
                    "errors": result["errors"][:10],
                },
            )

        summary = {
            "total_rows": result["total"],
            "valid_trades": result["imported"],
            "duplicates_found": result["duplicates"],
            "errors": len(result["errors"]),
        }
        if not sleeve_id:
            summary["accounts_created"] = result["accounts_created"]
            summary["strategies_created"] = result["strategies_created"]
            summary["sleeves_created"] = result["sleeves_created"]

        response = {
            "status": "success",
            "mode": mode,
            "routing": "single-sleeve" if sleeve_id else "auto-route",
            "summary": summary,
        }

        if mode == "VALIDATE":
            response["message"] = "Validation passed, ready to import"
            if result["errors"]:
                response["validation_warnings"] = result["errors"][:10]
        else:
            response["message"] = f"Successfully imported {result['imported']} trades"
            response["sync_log_id"] = result["sync_log_id"]

            affected = result.get("affected_sleeve_ids", [])
            if not affected and sleeve_id:
                affected = [sleeve_id]
            rebuild_for_sleeves(db, affected)

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Import processing failed: {str(e)}"
        )


# ---------------------------------------------------------------------------
# Manual Google Sheets sync
# ---------------------------------------------------------------------------


@router.post("/sync-daily")
def sync_daily(
    client_id: str = Query(..., description="Client ID"),
    sleeve_id: str = Query(..., description="Sleeve ID to sync trades into"),
    sheet_id: str = Query(..., description="Google Sheet ID"),
    range_name: str = Query(
        "Sheet1", description="Sheet range, e.g. Sheet1 or Sheet1!A:H"
    ),
    db: Session = Depends(get_db),
):
    """Sync trades from a Google Sheet into the specified sleeve."""
    sleeve = _sleeve_for_client(db, sleeve_id, client_id)
    if not sleeve:
        raise HTTPException(
            status_code=404,
            detail=f"Sleeve {sleeve_id} not found for client {client_id}",
        )

    try:
        result = run_daily_sync(
            db=db,
            sleeve_id=sleeve_id,
            sheet_id=sheet_id,
            range_name=range_name,
        )
    except Exception as e:
        logger.error(f"Daily sync failed: {e}")
        raise HTTPException(status_code=502, detail=f"Sync failed: {str(e)}")

    if not result["success"]:
        raise HTTPException(
            status_code=400,
            detail={"message": "Sync import failed", "errors": result["errors"][:10]},
        )

    rebuild_for_sleeves(db, [sleeve_id])

    return {
        "status": "success",
        "message": f"Synced {result['imported']} new trades from Google Sheets",
        "summary": {
            "total_rows": result["total"],
            "imported": result["imported"],
            "duplicates_skipped": result["duplicates"],
            "errors": len(result["errors"]),
        },
        "sync_log_id": result["sync_log_id"],
    }


# ---------------------------------------------------------------------------
# Sync logs
# ---------------------------------------------------------------------------


@router.get("/sync-logs")
def get_sync_logs(
    client_id: str = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Get import/sync logs (all logs; client_id reserved for future filtering)."""
    try:
        total = db.query(SyncLog).count()
        logs = (
            db.query(SyncLog)
            .order_by(SyncLog.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return {
            "total": total,
            "logs": [
                {
                    "id": log.id,
                    "import_type": log.import_type,
                    "status": log.status,
                    "rows_processed": log.rows_processed,
                    "rows_success": log.rows_success,
                    "rows_failed": log.rows_failed,
                    "error_details": log.error_details,
                    "created_at": log.created_at,
                }
                for log in logs
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch sync logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch logs")


# ---------------------------------------------------------------------------
# SheetSyncConfig CRUD — register/manage automated daily sync sources
# ---------------------------------------------------------------------------


class SyncConfigCreate(BaseModel):
    sleeve_id: str
    sheet_id: str
    range_name: str = "Sheet1"
    enabled: bool = True


class SyncConfigUpdate(BaseModel):
    enabled: bool


@router.post("/sync-configs", status_code=201)
def create_sync_config(body: SyncConfigCreate, db: Session = Depends(get_db)):
    """Register a Google Sheet → sleeve mapping for automated daily sync."""
    sleeve = db.query(Sleeve).filter(Sleeve.id == body.sleeve_id).first()
    if not sleeve:
        raise HTTPException(status_code=404, detail="Sleeve not found")

    cfg = SheetSyncConfig(
        id=str(uuid.uuid4()),
        sleeve_id=body.sleeve_id,
        sheet_id=body.sheet_id,
        range_name=body.range_name,
        enabled=body.enabled,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.get("/sync-configs")
def list_sync_configs(
    client_id: str = Query(None, description="Filter by client ID"),
    db: Session = Depends(get_db),
):
    """List all sheet sync configurations, optionally filtered by client."""
    q = db.query(SheetSyncConfig)
    if client_id:
        q = (
            q.join(Sleeve, SheetSyncConfig.sleeve_id == Sleeve.id)
            .join(Account, Sleeve.account_id == Account.id)
            .filter(Account.client_id == client_id)
        )
    return q.order_by(SheetSyncConfig.created_at.desc()).all()


@router.patch("/sync-configs/{config_id}")
def update_sync_config(
    config_id: str,
    body: SyncConfigUpdate,
    db: Session = Depends(get_db),
):
    """Enable or disable an automated sync config."""
    cfg = db.query(SheetSyncConfig).filter(SheetSyncConfig.id == config_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Sync config not found")
    cfg.enabled = body.enabled
    db.commit()
    db.refresh(cfg)
    return cfg


@router.delete("/sync-configs/{config_id}", status_code=204)
def delete_sync_config(config_id: str, db: Session = Depends(get_db)):
    """Remove a sync config."""
    cfg = db.query(SheetSyncConfig).filter(SheetSyncConfig.id == config_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Sync config not found")
    db.delete(cfg)
    db.commit()


# ---------------------------------------------------------------------------
# Weekly snapshot rebuild
# ---------------------------------------------------------------------------


@router.post("/rebuild-performance")
def rebuild_performance(
    account_id: str = Query(None, description="Rebuild one account; omit for all"),
    db: Session = Depends(get_db),
):
    """Rebuild the daily valuation rows (``perf.daily_valuation``).

    Replaces every reconstructed row from the trades and price history on
    file. Days captured from the brokerage are kept as captured; only their
    flows and returns are refreshed. Idempotent — safe to run after correcting
    historical trades or loading more price history.
    """
    service = PerformanceBuildService(db)
    try:
        if account_id:
            written = {account_id: service.rebuild_account(account_id)}
        else:
            written = service.rebuild_all()
        return {
            "status": "success",
            "accounts_rebuilt": len(written),
            "rows_written": sum(written.values()),
        }
    except Exception as e:
        logger.error(f"Performance rebuild failed: {e}")
        raise HTTPException(status_code=500, detail=f"Rebuild failed: {str(e)}")
