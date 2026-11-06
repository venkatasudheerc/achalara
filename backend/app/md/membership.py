"""Index membership from the funds that hold each index.

Each run downloads the funds' daily holdings, keeps every file as received in
``md.source_file``, and brings ``md.index_member`` (who is in each index now)
and ``md.index_member_hist`` (when each joined and left) up to date. The
Russell 3000 is the Russell 1000 together with the Russell 2000: its own fund
holds a sample, so it is never read for membership.

A file is only applied when its member count is in the range expected for
that index, so a broken or truncated download can never empty an index.
State Street's S&P 500 fund is read as an independent check on iShares'.
"""
import gzip
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.md import sources
from app.md.jobs import tracked_run
from app.md.models import (
    IndexDef,
    IndexMember,
    IndexMemberHist,
    Security,
    SecuritySymbol,
    SecuritySymbolHist,
    US_MARKET,
    SourceFile,
)
from app.md.readers import Holding, read_ishares_csv, read_ssga_xlsx

logger = logging.getLogger(__name__)

JOB = "md_index_membership"

READERS = {"ishares": read_ishares_csv, "ssga": read_ssga_xlsx}


@dataclass
class Outcome:
    """What one run did, index by index; also what System status and the CLI print."""

    applied: Dict[str, Tuple[date, int, int, int]] = field(
        default_factory=dict
    )  # as_of, members, joined, left
    refused: Dict[str, str] = field(default_factory=dict)
    check: Optional[str] = None
    requests: int = 0
    rows_written: int = 0

    def summary(self) -> str:
        parts = [
            f"{code} {as_of}: {members} members (+{joined} -{left})"
            for code, (as_of, members, joined, left) in self.applied.items()
        ]
        parts += [f"{code} not applied: {why}" for code, why in self.refused.items()]
        if self.check:
            parts.append(self.check)
        return "; ".join(parts)


class MembershipService:
    def __init__(self, db: Session):
        self.db = db

    # -- the run -------------------------------------------------------

    def run(self) -> Outcome:
        outcome = Outcome()
        with tracked_run(self.db, JOB) as run:
            indices = self.db.query(IndexDef).order_by(IndexDef.code).all()
            for index in indices:
                if index.method == "fund_file":
                    self._from_fund(index, outcome)
            for index in indices:
                if index.method == "union":
                    self._from_parts(index, outcome)
            self._check_against_second_fund(outcome)
            run.requests = outcome.requests
            run.rows_written = outcome.rows_written
            run.note = outcome.summary()[:2000]
            if outcome.refused:
                run.outcome = "failed"
                logger.warning(
                    "Index membership not fully applied: %s", outcome.summary()
                )
            elif outcome.check:
                logger.warning("Index membership check: %s", outcome.check)
        return outcome

    # -- one index -------------------------------------------------------

    def _from_fund(self, index: IndexDef, outcome: Outcome) -> None:
        source, name = index.source.split(":", 1)
        stored, as_of, holdings = self._fetch(source, name, outcome)
        if stored is None:
            outcome.refused[index.code] = f"{name} could not be read"
            return
        members = {
            self._security_for(h, as_of, source).id
            for h in holdings
            if h.kind == "stock"
        }
        self._apply(index, members, as_of, stored.id, outcome)

    def _from_parts(self, index: IndexDef, outcome: Outcome) -> None:
        parts = [p.strip() for p in (index.parts or "").split(",") if p.strip()]
        if any(part not in outcome.applied for part in parts):
            outcome.refused[index.code] = "a part was not applied this run"
            return
        members: Set[str] = set()
        for part in parts:
            members |= {
                row[0]
                for row in self.db.query(IndexMember.security_id).filter(
                    IndexMember.index_code == part
                )
            }
        as_of = max(outcome.applied[part][0] for part in parts)
        self._apply(index, members, as_of, None, outcome)

    def _apply(
        self,
        index: IndexDef,
        members: Set[str],
        as_of: date,
        file_id: Optional[str],
        outcome: Outcome,
    ) -> None:
        """Bring one index's current members and their history up to ``as_of``."""
        low, high = index.expected_min or 1, index.expected_max or 10**6
        if not low <= len(members) <= high:
            outcome.refused[
                index.code
            ] = f"{len(members)} members, expected {low} to {high}"
            return
        latest = (
            self.db.query(func.max(IndexMember.since))
            .filter(IndexMember.index_code == index.code)
            .scalar()
        )
        if latest is not None and as_of < latest:
            outcome.refused[
                index.code
            ] = f"file as of {as_of} is older than what is on file ({latest})"
            return
        current = {
            row.security_id: row
            for row in self.db.query(IndexMember).filter(
                IndexMember.index_code == index.code
            )
        }
        joined = members - set(current)
        left = set(current) - members
        for security_id in joined:
            self.db.add(
                IndexMember(index_code=index.code, security_id=security_id, since=as_of)
            )
            self.db.add(
                IndexMemberHist(
                    index_code=index.code,
                    security_id=security_id,
                    valid_from=as_of,
                    source_file_id=file_id,
                )
            )
        for security_id in left:
            self.db.delete(current[security_id])
            # The span ends on the first day the security is no longer a member.
            self.db.query(IndexMemberHist).filter(
                IndexMemberHist.index_code == index.code,
                IndexMemberHist.security_id == security_id,
                IndexMemberHist.valid_to.is_(None),
            ).update({IndexMemberHist.valid_to: as_of})
        self.db.commit()
        outcome.applied[index.code] = (as_of, len(members), len(joined), len(left))
        outcome.rows_written += 2 * (len(joined) + len(left))

    # -- files and securities -------------------------------------------

    def _fetch(
        self, source: str, name: str, outcome: Outcome
    ) -> Tuple[Optional[SourceFile], Optional[date], List[Holding]]:
        """Download, read and keep one file; the stored row, its date and its holdings."""
        try:
            content = sources.fetch(sources.FUND_FILES[name].url)
            outcome.requests += 1
            as_of, holdings = READERS[source](content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read the %s holdings file: %s", name, exc)
            return None, None, []
        digest = hashlib.sha256(content).hexdigest()
        stored = (
            self.db.query(SourceFile)
            .filter(
                SourceFile.source == source,
                SourceFile.name == name,
                SourceFile.as_of == as_of,
            )
            .first()
        )
        if stored is None:
            stored = SourceFile(
                source=source,
                name=name,
                as_of=as_of,
                content=gzip.compress(content),
                sha256=digest,
                rows=len(holdings),
                fetched_at=datetime.now(timezone.utc),
            )
            self.db.add(stored)
            self.db.flush()
            outcome.rows_written += 1
        return stored, as_of, holdings

    def _security_for(self, holding: Holding, as_of: date, source: str) -> Security:
        """The security a holding names, created the first time it is seen."""
        known = (
            self.db.query(SecuritySymbol)
            .filter(
                SecuritySymbol.market_code == US_MARKET,
                SecuritySymbol.symbol == holding.symbol,
            )
            .first()
        )
        if known is not None:
            return self.db.get(Security, known.security_id)
        security = Security(
            name=holding.name or holding.symbol,
            kind=holding.kind,
            exchange=holding.exchange,
        )
        self.db.add(security)
        self.db.flush()
        self.db.add(SecuritySymbol(security_id=security.id, symbol=holding.symbol))
        self.db.add(
            SecuritySymbolHist(
                security_id=security.id,
                symbol=holding.symbol,
                valid_from=as_of,
                source=source,
            )
        )
        return security

    # -- the check -------------------------------------------------------

    def _check_against_second_fund(self, outcome: Outcome) -> None:
        """Compare iShares' S&P 500 with State Street's; differences are reported, not applied."""
        if "SP500" not in outcome.applied:
            return
        stored, as_of, holdings = self._fetch("ssga", "SPY", outcome)
        if stored is None:
            outcome.check = (
                "S&P 500 check skipped: the State Street file could not be read"
            )
            return
        self.db.commit()
        theirs = {h.symbol for h in holdings}
        ours = {
            row[0]
            for row in self.db.query(SecuritySymbol.symbol)
            .join(IndexMember, IndexMember.security_id == SecuritySymbol.security_id)
            .filter(SecuritySymbol.market_code == US_MARKET)
            .filter(IndexMember.index_code == "SP500")
        }
        only_ours, only_theirs = sorted(ours - theirs), sorted(theirs - ours)
        if only_ours or only_theirs:
            outcome.check = (
                f"S&P 500: iShares and State Street ({as_of}) differ — "
                f"only iShares {only_ours[:10]}, only State Street {only_theirs[:10]}"
            )


def run_index_membership(db: Session) -> Outcome:
    return MembershipService(db).run()
