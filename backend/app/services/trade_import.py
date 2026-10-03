"""Trade import service — CSV uploads, behind the connector seam.

Thin orchestration only: the ``CSVConnector`` turns uploaded bytes into
normalized trades, and ``IngestionService`` owns the shared VALIDATE→IMPORT /
dedup / route / persist pipeline. The public methods and result contract are
unchanged so existing routes/tests keep working.
"""
import logging
from typing import Dict

from sqlalchemy.orm import Session

from app.connectors.csv_connector import CSVConnector
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)


class TradeImportService:
    """Imports trades from CSV files via the connector + ingestion pipeline."""

    def __init__(self, db: Session):
        self.db = db
        self.connector = CSVConnector()
        self.ingestion = IngestionService(db)

    def import_from_file(
        self,
        file_content: bytes,
        sleeve_id: str,
        mode: str = "IMPORT",
        import_type: str = "HISTORICAL",
    ) -> Dict:
        """Import trades from a CSV file into a single sleeve.

        Returns ``{success, total, imported, duplicates, errors, sync_log_id}``
        plus ``affected_sleeve_ids``.
        """
        try:
            trades, errors, row_count = self.connector.parse_transactions(file_content)
        except ValueError as e:
            return {
                "success": False,
                "total": 0,
                "imported": 0,
                "duplicates": 0,
                "errors": [f"Import error: {str(e)}"],
                "sync_log_id": None,
                "affected_sleeve_ids": [],
            }

        result = self.ingestion.ingest_to_sleeve(
            trades,
            sleeve_id,
            mode=mode,
            import_type=import_type,
            total_rows=row_count,
            prior_error_count=len(errors),
        )
        # Preserve the legacy no-valid-rows message and "errors at the end" order.
        if not trades and result["success"] is False:
            result["errors"] = [
                e for e in result["errors"] if e != "No valid trades found"
            ]
            if "No valid trades found in CSV" not in result["errors"]:
                result["errors"].insert(0, "No valid trades found in CSV")
        result["errors"].extend(errors)
        return result

    def import_routed(
        self,
        file_content: bytes,
        client_id: str,
        mode: str = "IMPORT",
        import_type: str = "HISTORICAL",
    ) -> Dict:
        """Import trades, auto-routing each row to its account + strategy.

        Returns the standard result dict plus ``accounts_created``,
        ``strategies_created``, ``sleeves_created`` and ``affected_sleeve_ids``.
        """
        try:
            trades, errors, row_count = self.connector.parse_transactions(file_content)
        except ValueError as e:
            return {
                "success": False,
                "total": 0,
                "imported": 0,
                "duplicates": 0,
                "errors": [f"Import error: {str(e)}"],
                "sync_log_id": None,
                "accounts_created": 0,
                "strategies_created": 0,
                "sleeves_created": 0,
                "affected_sleeve_ids": [],
            }

        result = self.ingestion.ingest_routed(
            trades,
            client_id,
            mode=mode,
            import_type=import_type,
            total_rows=row_count,
            prior_error_count=len(errors),
        )
        # Legacy ordering: CSV validation errors precede routing errors.
        result["errors"] = errors + result["errors"]
        return result
