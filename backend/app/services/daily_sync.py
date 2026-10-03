"""Reusable daily sync logic shared by the route handler and the scheduler job.

Sits on the connector seam: the ``SheetsConnector`` fetches and normalizes the
sheet, then the shared ``IngestionService`` validates/dedups/persists — the same
pipeline every other source uses.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.connectors.sheets_connector import SheetsConnector
from app.services.ingestion_service import IngestionService
from app.models.sheet_sync_config import SheetSyncConfig

logger = logging.getLogger(__name__)


def run_daily_sync(
    db: Session,
    sleeve_id: str,
    sheet_id: str,
    range_name: str = "Sheet1",
) -> dict:
    """
    Fetch trades from a Google Sheet and import new ones into the given sleeve.

    Returns the same result dict as the ingestion pipeline, plus a top-level
    'sheet_rows' key with the raw row count fetched.

    Raises ValueError / RuntimeError so callers can translate to HTTP errors.
    """
    connector = SheetsConnector()
    trades, errors, sheet_rows = connector.fetch_sheet(sheet_id, range_name)

    if sheet_rows == 0:
        return {
            "success": True,
            "total": 0,
            "imported": 0,
            "duplicates": 0,
            "errors": [],
            "sync_log_id": None,
            "affected_sleeve_ids": [],
            "sheet_rows": 0,
        }

    ingestion = IngestionService(db)
    result = ingestion.ingest_to_sleeve(
        trades,
        sleeve_id,
        mode="IMPORT",
        import_type="DAILY",
        total_rows=sheet_rows,
        prior_error_count=len(errors),
    )
    result["errors"].extend(errors)
    result["sheet_rows"] = sheet_rows
    return result


def run_all_enabled_syncs(db: Session) -> None:
    """Called by the APScheduler job — iterates all enabled SheetSyncConfig rows."""
    configs = db.query(SheetSyncConfig).filter(SheetSyncConfig.enabled.is_(True)).all()
    logger.info(f"Daily sync job starting: {len(configs)} config(s) to process")

    for cfg in configs:
        try:
            result = run_daily_sync(
                db=db,
                sleeve_id=cfg.sleeve_id,
                sheet_id=cfg.sheet_id,
                range_name=cfg.range_name,
            )
            cfg.last_synced_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(
                f"Synced config {cfg.id}: imported={result['imported']}, "
                f"duplicates={result['duplicates']}"
            )
        except Exception as exc:
            logger.error(f"Daily sync failed for config {cfg.id}: {exc}")
            db.rollback()
