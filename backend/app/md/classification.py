"""Each security's sector and industry, from every source, resolved to one answer.

Sources, and which wins:

- **Sector:** manual, then iShares (the official GICS sector of index members,
  read from the stored holdings files), then the sector of the security's
  Webull industry, then the SEC industry code mapped to a sector.
- **Industry:** manual, then Webull's company profile, then the SEC's industry
  description.

A Webull industry is placed under the GICS sector most of its index members
carry ("ishares_majority"), so the mapping is worked out from evidence, not
written by hand; a manual placement is never recomputed. Each source's view
is kept in ``md.security_classification_hist``; the resolved answer is the
current ``md.security_classification``.
"""
import gzip
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.md.jobs import tracked_run
from app.md.models import (
    Company,
    IndexDef,
    Industry,
    Security,
    SecurityClassification,
    SecurityClassificationHist,
    SecuritySymbol,
    US_MARKET,
    SourceFile,
)
from app.md.readers import read_ishares_csv
from app.utils.symbols import webull_symbol
from app.md.sectors import ishares_sector, sic_sector
from app.md.webull import (
    WebullClient,
    WebullError,
    WebullRefused,
    WebullUnreachable,
)

logger = logging.getLogger(__name__)

JOB = "md_classification"

PROFILES_PER_NIGHT = 400  # new securities first; Saturdays also refresh the oldest
REFRESH_AFTER = timedelta(days=30)
UNREACHABLE_LIMIT = 5  # failures in a row before the profiles stop for the night
SECTOR_ORDER = ("manual", "ishares", "webull", "sec")
INDUSTRY_ORDER = ("manual", "webull", "sec")


class ClassificationService:
    def __init__(self, db: Session, webull: Optional[WebullClient] = None):
        self.db = db
        self.webull = webull or WebullClient()
        self.notes = []
        self.rows = 0
        self._written = (
            {}
        )  # (security_id, source) -> row added in this run, not yet flushed

    def run(self, today: date, refresh: bool = False) -> str:
        with tracked_run(self.db, JOB) as run:
            try:
                self._webull_profiles(today, refresh)
            except WebullRefused:
                self.notes.append(
                    "Webull refused (too many requests); stopped for tonight"
                )
                run.outcome = "failed"
            self._from_index_files(today)
            self._from_sec(today)
            self._place_industries()
            self._resolve(today)
            run.requests = self.webull.requests
            run.rows_written = self.rows
            run.note = "; ".join(self.notes)[:2000]
        return "; ".join(self.notes)

    # -- what each source says ------------------------------------------------

    def _record(
        self,
        security_id: str,
        source: str,
        today: date,
        *,
        sector_code=None,
        industry_id=None,
        raw_sector=None,
        raw_industry=None,
        raw_code=None,
    ) -> None:
        """Open a new span when a source's view of a security changes; else leave it."""
        open_row = self._written.get((security_id, source))
        if open_row is None:
            open_row = (
                self.db.query(SecurityClassificationHist)
                .filter(
                    SecurityClassificationHist.security_id == security_id,
                    SecurityClassificationHist.source == source,
                    SecurityClassificationHist.valid_to.is_(None),
                )
                .first()
            )
        if open_row is not None and (open_row.sector_code, open_row.industry_id) == (
            sector_code,
            industry_id,
        ):
            return
        if open_row is not None:
            if open_row.valid_from == today:
                self.db.delete(open_row)
                self.db.flush()
            else:
                open_row.valid_to = today
        row = SecurityClassificationHist(
            security_id=security_id,
            source=source,
            valid_from=today,
            sector_code=sector_code,
            industry_id=industry_id,
            raw_sector=raw_sector,
            raw_industry=raw_industry,
            raw_code=raw_code,
        )
        self.db.add(row)
        self._written[(security_id, source)] = row
        self.rows += 1

    def _industry(
        self,
        scheme: str,
        name: str,
        group: Optional[str] = None,
        code: Optional[str] = None,
    ) -> Industry:
        found = (
            self.db.query(Industry)
            .filter(Industry.scheme == scheme, Industry.name == name)
            .first()
        )
        if found is None:
            found = Industry(
                scheme=scheme, name=name, industry_group=group, source_code=code
            )
            self.db.add(found)
            self.db.flush()
        return found

    def _webull_profiles(self, today: date, refresh: bool) -> None:
        if not self.webull.configured():
            self.notes.append("Webull not configured; profiles skipped")
            return
        query = (
            self.db.query(Security, SecuritySymbol.symbol)
            .join(SecuritySymbol, SecuritySymbol.security_id == Security.id)
            .filter(Security.market_code == US_MARKET)
            .filter(Security.kind.in_(("stock", "adr", "preferred")))
        )
        stale = datetime.now(timezone.utc) - REFRESH_AFTER
        due = (
            query.filter(Security.profile_checked_at.is_(None))
            .limit(PROFILES_PER_NIGHT)
            .all()
        )
        if refresh and len(due) < PROFILES_PER_NIGHT:
            due += (
                query.filter(Security.profile_checked_at < stale)
                .order_by(Security.profile_checked_at)
                .limit(PROFILES_PER_NIGHT - len(due))
                .all()
            )
        fetched = 0
        unreachable = 0
        for security, symbol in due:
            try:
                profile = self.webull.get(
                    "/market-data/fundamentals/company-profiles/get",
                    {"symbol": webull_symbol(symbol), "category": "US_STOCK"},
                )
                unreachable = 0
            except WebullUnreachable:
                # No answer is not "no profile": leave it to be asked again.
                unreachable += 1
                if unreachable >= UNREACHABLE_LIMIT:
                    self.notes.append(
                        "Webull not answering; profiles stopped for tonight"
                    )
                    break
                continue
            except WebullRefused:
                raise
            except WebullError:
                profile = {}
            security.profile_checked_at = datetime.now(timezone.utc)
            levels = [x for x in (profile.get("industries") or []) if x]
            if levels:
                group, name = (levels[0], levels[-1])
                industry = self._industry(
                    "webull", name, group=group if len(levels) > 1 else None
                )
                self._record(
                    security.id,
                    "webull",
                    today,
                    industry_id=industry.id,
                    raw_sector=group,
                    raw_industry=" > ".join(levels),
                )
            fetched += 1
            if fetched % 50 == 0:
                self.db.commit()
        self.db.commit()
        self.notes.append(f"Webull profiles: {fetched}")

    def _from_index_files(self, today: date) -> None:
        """The GICS sector of every index member, from the latest stored fund files."""
        counted = 0
        for index in self.db.query(IndexDef).filter(IndexDef.method == "fund_file"):
            source, name = (index.source or ":").split(":", 1)
            if source != "ishares":
                continue
            latest = (
                self.db.query(SourceFile)
                .filter(SourceFile.source == "ishares", SourceFile.name == name)
                .order_by(SourceFile.as_of.desc())
                .first()
            )
            if latest is None:
                continue
            _, holdings = read_ishares_csv(gzip.decompress(latest.content))
            symbols = {
                row.symbol: row.security_id for row in self.db.query(SecuritySymbol)
            }
            for holding in holdings:
                security_id = symbols.get(holding.symbol)
                sector = ishares_sector(holding.sector)
                if security_id and sector:
                    self._record(
                        security_id,
                        "ishares",
                        today,
                        sector_code=sector,
                        raw_sector=holding.sector,
                    )
                    counted += 1
        self.db.commit()
        self.notes.append(f"iShares sectors: {counted}")

    def _from_sec(self, today: date) -> None:
        """The SEC's industry code for securities linked to a company."""
        counted = 0
        rows = (
            self.db.query(Security.id, Company.sic_code, Company.sic_description)
            .join(Company, Company.id == Security.company_id)
            .filter(Company.sic_code.isnot(None))
        )
        for security_id, sic, description in rows:
            industry = self._industry("sec", description or f"SIC {sic}", code=sic)
            if industry.sector_code is None and industry.sector_basis != "manual":
                industry.sector_code, industry.sector_basis = sic_sector(sic), "sic_map"
            self._record(
                security_id,
                "sec",
                today,
                sector_code=industry.sector_code,
                industry_id=industry.id,
                raw_industry=description,
                raw_code=sic,
            )
            counted += 1
        self.db.commit()
        self.notes.append(f"SEC industries: {counted}")

    # -- Webull industries placed under sectors -------------------------------

    def _place_industries(self) -> None:
        """Put each Webull industry under the GICS sector most of its index members carry."""
        open_rows = (
            self.db.query(SecurityClassificationHist)
            .filter(
                SecurityClassificationHist.valid_to.is_(None),
                SecurityClassificationHist.source.in_(("webull", "ishares")),
            )
            .all()
        )
        industry_of, sector_of = {}, {}
        for row in open_rows:
            if row.source == "webull":
                industry_of[row.security_id] = row.industry_id
            else:
                sector_of[row.security_id] = row.sector_code
        votes: Dict[str, Counter] = defaultdict(Counter)
        for security_id, industry_id in industry_of.items():
            if security_id in sector_of:
                votes[industry_id][sector_of[security_id]] += 1
        placed = 0
        for industry in self.db.query(Industry).filter(Industry.scheme == "webull"):
            if industry.sector_basis == "manual":
                continue
            if votes.get(industry.id):
                sector = votes[industry.id].most_common(1)[0][0]
                if (industry.sector_code, industry.sector_basis) != (
                    sector,
                    "ishares_majority",
                ):
                    industry.sector_code, industry.sector_basis = (
                        sector,
                        "ishares_majority",
                    )
                    placed += 1
        self.db.commit()
        unplaced = (
            self.db.query(func.count(Industry.id))
            .filter(Industry.scheme == "webull", Industry.sector_code.is_(None))
            .scalar()
        )
        self.notes.append(f"industries placed {placed}, without a sector {unplaced}")

    # -- the answer ---------------------------------------------------------------

    def _resolve(self, today: date) -> None:
        """Write each security's current sector and industry from the precedence."""
        industries = {i.id: i for i in self.db.query(Industry)}
        views: Dict[str, Dict[str, SecurityClassificationHist]] = defaultdict(dict)
        for row in self.db.query(SecurityClassificationHist).filter(
            SecurityClassificationHist.valid_to.is_(None)
        ):
            views[row.security_id][row.source] = row
        current = {c.security_id: c for c in self.db.query(SecurityClassification)}
        changed = 0
        for security_id, by_source in views.items():
            sector, sector_source = self._pick_sector(by_source, industries)
            industry_id, industry_source = self._pick_industry(by_source)
            row = current.get(security_id)
            if row is None:
                row = SecurityClassification(security_id=security_id, as_of=today)
                self.db.add(row)
            if (
                row.sector_code,
                row.industry_id,
                row.sector_source,
                row.industry_source,
            ) != (sector, industry_id, sector_source, industry_source):
                row.sector_code, row.industry_id = sector, industry_id
                row.sector_source, row.industry_source = sector_source, industry_source
                row.as_of = today
                changed += 1
        self.db.commit()
        self.rows += changed
        self.notes.append(f"classifications changed {changed}")

    @staticmethod
    def _pick_sector(by_source, industries) -> Tuple[Optional[str], Optional[str]]:
        for source in SECTOR_ORDER:
            row = by_source.get(source)
            if row is None:
                continue
            sector = row.sector_code
            if sector is None and row.industry_id in industries:
                sector = industries[row.industry_id].sector_code
            if sector:
                return sector, source
        return None, None

    @staticmethod
    def _pick_industry(by_source) -> Tuple[Optional[str], Optional[str]]:
        for source in INDUSTRY_ORDER:
            row = by_source.get(source)
            if row is not None and row.industry_id:
                return row.industry_id, source
        return None, None

    # -- by hand ------------------------------------------------------------------

    def set_manual(
        self,
        symbol: str,
        sector_code: Optional[str],
        industry_name: Optional[str],
        today: date,
    ) -> None:
        link = (
            self.db.query(SecuritySymbol)
            .filter(
                SecuritySymbol.market_code == US_MARKET, SecuritySymbol.symbol == symbol
            )
            .first()
        )
        if link is None:
            raise LookupError(f"{symbol} is not in the security master")
        industry = self._industry("manual", industry_name) if industry_name else None
        if industry is not None and sector_code and industry.sector_code is None:
            industry.sector_code, industry.sector_basis = sector_code, "manual"
        self._record(
            link.security_id,
            "manual",
            today,
            sector_code=sector_code,
            industry_id=industry.id if industry else None,
            raw_industry=industry_name,
        )
        self.db.commit()
        self._resolve(today)


def run_classification(db: Session, today: date, refresh: bool = False) -> str:
    return ClassificationService(db).run(today, refresh)
