"""Who each security is: Webull's id, the SEC company behind it, and its FIGI.

Runs daily before the market opens. Only securities already in the master
(index members and client holdings) are filled in; nothing is added here.
A ticker change shows up as Webull's same instrument id under a new symbol,
and becomes a new row in ``md.security_symbol_hist``, not a new security.
"""
import logging
import time
import urllib.error
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.md.config import settings
from app.md import sources
from app.md.jobs import tracked_run
from app.md.models import (
    Company,
    Security,
    SecuritySymbol,
    SecuritySymbolHist,
    US_MARKET,
)
from app.utils.symbols import app_symbol, figi_symbol
from app.md.webull import WebullClient, WebullError, WebullRefused

logger = logging.getLogger(__name__)

JOB = "md_identifiers"

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

SUBMISSIONS_PER_RUN = 600  # the first runs work through the backlog over a few days
FIGI_PER_RUN = 300
_SEC_PACE = 0.15  # the SEC allows 10 a second


class IdentifierService:
    def __init__(self, db: Session, webull: Optional[WebullClient] = None):
        self.db = db
        self.webull = webull or WebullClient()
        self.notes: List[str] = []
        self.requests = 0
        self.rows = 0

    def run(self, today: date) -> str:
        with tracked_run(self.db, JOB) as run:
            try:
                self._webull_instruments(today)
            except WebullRefused:
                self.notes.append(
                    "Webull refused (too many requests); stopped for today"
                )
                run.outcome = "failed"
            except WebullError as exc:
                self.notes.append(f"Webull list not read ({exc}); tried again tomorrow")
                run.outcome = "failed"
            self._sec_companies()
            self._sec_submissions()
            self._figis()
            run.requests = self.requests + self.webull.requests
            run.rows_written = self.rows
            run.note = "; ".join(self.notes)[:2000]
        return "; ".join(self.notes)

    # -- Webull ----------------------------------------------------------

    def _webull_instruments(self, today: date) -> None:
        if not self.webull.configured():
            self.notes.append("Webull not configured; skipped")
            return
        symbols = {
            row.symbol: row.security_id
            for row in self.db.query(SecuritySymbol).filter(
                SecuritySymbol.market_code == US_MARKET
            )
        }
        securities = {s.id: s for s in self.db.query(Security)}
        by_webull = {s.webull_id: s for s in securities.values() if s.webull_id}
        linked = renamed = 0
        for sub_category in ("COMMON_STOCK", "ETF"):
            key = None
            while True:
                page = self.webull.get(
                    "/trading/instruments/stocks/profiles/list",
                    {
                        "category": "US_STOCK",
                        "sub_category": sub_category,
                        "pagination_key": key,
                    },
                )
                for row in page.get("data") or []:
                    symbol = app_symbol(row.get("symbol") or "")
                    webull_id = str(row.get("instrument_id") or "")
                    if not symbol or not webull_id:
                        continue
                    known = by_webull.get(webull_id)
                    if known is not None:
                        current = self.db.get(SecuritySymbol, known.id)
                        if (
                            current
                            and current.symbol != symbol
                            and symbol not in symbols
                        ):
                            self._rename(known, current, symbol, today)
                            symbols[symbol] = known.id
                            renamed += 1
                        continue
                    security = securities.get(symbols.get(symbol))
                    if security is None or security.webull_id:
                        continue
                    security.webull_id = webull_id
                    by_webull[webull_id] = security
                    if sub_category == "ETF" and security.kind in ("stock", "other"):
                        security.kind = "etf"
                    if not security.exchange and row.get("exchange_code"):
                        security.exchange = row["exchange_code"]
                    linked += 1
                self.db.commit()
                key = page.get("pagination_key")
                if not key or not page.get("data"):
                    break
        self.rows += linked + 2 * renamed
        self.notes.append(f"Webull: {linked} linked, {renamed} ticker changes")

    def _rename(
        self, security: Security, current: SecuritySymbol, symbol: str, today: date
    ) -> None:
        """A new ticker for the same security: close the old span, open a new one."""
        self.db.query(SecuritySymbolHist).filter(
            SecuritySymbolHist.security_id == security.id,
            SecuritySymbolHist.valid_to.is_(None),
        ).update({SecuritySymbolHist.valid_to: today})
        current.symbol = symbol
        self.db.add(
            SecuritySymbolHist(
                security_id=security.id,
                symbol=symbol,
                valid_from=today,
                source="webull",
            )
        )
        logger.info("Ticker change detected for a security in the master")

    # -- SEC ---------------------------------------------------------------

    def _sec_companies(self) -> None:
        """Link securities to SEC companies (CIK), from the SEC's daily tickers file."""
        if not settings.sec_contact_email:
            self.notes.append("SEC contact email not set; SEC skipped")
            return
        try:
            data = sources.sec(SEC_TICKERS_URL)
            self.requests += 1
        except (urllib.error.URLError, ValueError) as exc:
            self.notes.append(f"SEC tickers file failed: {type(exc).__name__}")
            return
        columns = {name: i for i, name in enumerate(data.get("fields") or [])}
        symbols = {
            row.symbol: row.security_id
            for row in self.db.query(SecuritySymbol).filter(
                SecuritySymbol.market_code == US_MARKET
            )
        }
        companies = {
            c.cik: c for c in self.db.query(Company).filter(Company.cik.isnot(None))
        }
        linked = 0
        for row in data.get("data") or []:
            cik = str(row[columns["cik"]]).zfill(10)
            security_id = symbols.get(app_symbol(str(row[columns["ticker"]])))
            if security_id is None:
                continue
            security = self.db.get(Security, security_id)
            if security.company_id:
                continue
            company = companies.get(cik)
            if company is None:
                company = Company(name=str(row[columns["name"]]), cik=cik)
                self.db.add(company)
                self.db.flush()
                companies[cik] = company
            security.company_id = company.id
            linked += 1
        self.db.commit()
        self.rows += linked
        self.notes.append(f"SEC: {linked} securities linked to companies")

    def _sec_submissions(self) -> None:
        """Each company's industry code and fiscal year end, a few hundred a run."""
        if not settings.sec_contact_email:
            return
        pending = (
            self.db.query(Company)
            .filter(Company.cik.isnot(None), Company.sic_code.is_(None))
            .limit(SUBMISSIONS_PER_RUN)
            .all()
        )
        done = 0
        for company in pending:
            try:
                data = sources.sec(SEC_SUBMISSIONS_URL.format(cik=company.cik))
                self.requests += 1
            except (urllib.error.URLError, ValueError):
                continue
            company.sic_code = (data.get("sic") or "")[:4] or None
            company.sic_description = (data.get("sicDescription") or "")[:120] or None
            company.fiscal_year_end = (data.get("fiscalYearEnd") or "")[:4] or None
            done += 1
            if done % 50 == 0:
                self.db.commit()
            time.sleep(_SEC_PACE)
        self.db.commit()
        self.rows += done
        if pending:
            self.notes.append(f"SEC: {done} company profiles")

    # -- OpenFIGI ------------------------------------------------------------

    def _figis(self) -> None:
        """The permanent id (composite FIGI) for securities without one."""
        pending = (
            self.db.query(Security, SecuritySymbol.symbol)
            .join(SecuritySymbol, SecuritySymbol.security_id == Security.id)
            .filter(Security.market_code == US_MARKET)
            .filter(Security.figi.is_(None))
            .limit(FIGI_PER_RUN)
            .all()
        )
        if not pending:
            return
        taken = {
            row[0]
            for row in self.db.query(Security.figi).filter(Security.figi.isnot(None))
        }
        batch_size, pace = (100, 0.3) if settings.openfigi_api_key else (10, 2.6)
        found = 0
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            jobs = [
                {
                    "idType": "TICKER",
                    "idValue": figi_symbol(symbol),
                    "exchCode": "US",
                }
                for _, symbol in batch
            ]
            try:
                answers = sources.figi(jobs)
                self.requests += 1
            except (urllib.error.URLError, ValueError) as exc:
                self.notes.append(f"OpenFIGI stopped: {type(exc).__name__}")
                break
            for (security, _), answer in zip(batch, answers):
                figis = {
                    item.get("compositeFIGI")
                    for item in answer.get("data") or []
                    if item.get("compositeFIGI")
                }
                if len(figis) == 1:
                    figi = figis.pop()
                    if figi not in taken:
                        security.figi = figi
                        taken.add(figi)
                        found += 1
            self.db.commit()
            time.sleep(pace)
        self.rows += found
        self.notes.append(f"OpenFIGI: {found} of {len(pending)}")


def run_identifiers(db: Session, today: date) -> str:
    return IdentifierService(db).run(today)
