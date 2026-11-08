"""Market data: identifiers and classification. Invented securities and stand-in sources only."""
import gzip
from datetime import date, datetime, timezone

import pytest

from app.md.config import settings
from app.md import sources
from app.md.classification import ClassificationService
from app.md.identifiers import IdentifierService
from app.md.models import (
    Company,
    IndexDef,
    Industry,
    JobRun,
    Sector,
    Security,
    SecurityClassification,
    SecurityClassificationHist,
    SecuritySymbol,
    SecuritySymbolHist,
    SourceFile,
)
from app.md.sectors import SECTORS, sic_sector
from app.md.webull import WebullRefused, WebullUnreachable
from tests.test_md_membership import ishares_csv, stock

DAY = date(2026, 10, 19)
NEXT = date(2026, 10, 20)


class FakeWebull:
    """Answers like Webull's v3 endpoints, from what each test puts in it."""

    def __init__(self, pages=None, profiles=None, refuse_after=None, silent=()):
        self.pages = pages or {}  # sub_category -> [page rows, ...]
        self.profiles = profiles or {}  # symbol (Webull spelling) -> industries list
        self.refuse_after = refuse_after
        self.silent = silent  # symbols, or "*", that get no answer (a timeout)
        self.requests = 0

    def configured(self):
        return True

    def get(self, path, query=None):
        self.requests += 1
        if self.refuse_after is not None and self.requests > self.refuse_after:
            raise WebullRefused(path)
        query = query or {}
        if path.endswith("/profiles/list"):
            pages = self.pages.get(query.get("sub_category"), [[]])
            index = int(query.get("pagination_key") or 0)
            rows = pages[index] if index < len(pages) else []
            return {
                "data": rows,
                "pagination_key": str(index + 1) if index + 1 < len(pages) else None,
            }
        if path.endswith("/company-profiles/get"):
            if "*" in self.silent or query["symbol"] in self.silent:
                raise WebullUnreachable(path)
            return {"industries": self.profiles.get(query["symbol"], [])}
        raise AssertionError(path)


@pytest.fixture
def master(db):
    """Sectors, the S&P 500 index, and a few securities by symbol."""
    db.add_all([Sector(code=c, name=n, sort=o) for c, n, o in SECTORS])
    db.add(
        IndexDef(
            code="SP500",
            name="S&P 500",
            owner="S&P",
            method="fund_file",
            source="ishares:IVV",
        )
    )
    made = {}
    for symbol, kind in (
        ("AAA", "stock"),
        ("BBB", "stock"),
        ("CCC", "stock"),
        ("OFF", "stock"),
        ("XYZ.B", "stock"),
        ("FUND", "other"),
    ):
        security = Security(name=f"{symbol} INC", kind=kind)
        db.add(security)
        db.flush()
        db.add(SecuritySymbol(security_id=security.id, symbol=symbol))
        db.add(
            SecuritySymbolHist(
                security_id=security.id,
                symbol=symbol,
                valid_from=date(2026, 10, 1),
                source="test",
            )
        )
        made[symbol] = security
    db.commit()
    return made


def ivv_file(db, lines, as_of=date(2026, 10, 16), name="IVV"):
    content = ishares_csv(as_of.strftime("%b %d, %Y"), lines)
    db.add(
        SourceFile(
            source="ishares",
            name=name,
            as_of=as_of,
            content=gzip.compress(content),
            sha256="x",
            rows=len(lines),
            fetched_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


def now(db, symbol):
    row = (
        db.query(SecurityClassification, Industry.name)
        .outerjoin(Industry, Industry.id == SecurityClassification.industry_id)
        .join(
            SecuritySymbol,
            SecuritySymbol.security_id == SecurityClassification.security_id,
        )
        .filter(SecuritySymbol.symbol == symbol)
        .first()
    )
    if row is None:
        return None
    c, industry = row
    return (c.sector_code, industry, c.sector_source, c.industry_source)


# -- identifiers ---------------------------------------------------------------


@pytest.fixture
def sec_off(monkeypatch):
    monkeypatch.setattr(settings, "sec_contact_email", "")
    monkeypatch.setattr(
        sources,
        "figi",
        lambda jobs: [{"warning": "No identifier found."} for _ in jobs],
    )
    monkeypatch.setattr("app.md.identifiers.time.sleep", lambda s: None)


def test_webull_ids_are_linked_across_pages_and_etfs_marked(db, master, sec_off):
    webull = FakeWebull(
        pages={
            "COMMON_STOCK": [
                [{"symbol": "AAA", "instrument_id": 1, "exchange_code": "NSQ"}],
                [
                    {"symbol": "XYZ B", "instrument_id": 2},
                    {"symbol": "NOTHELD", "instrument_id": 3},
                ],
            ],
            "ETF": [[{"symbol": "FUND", "instrument_id": 4}]],
        }
    )
    IdentifierService(db, webull).run(DAY)
    ids = {
        s.symbol: (sec.webull_id, sec.kind, sec.exchange)
        for s, sec in db.query(SecuritySymbol, Security).join(Security)
    }
    assert ids["AAA"] == ("1", "stock", "NSQ")
    assert ids["XYZ.B"][0] == "2"  # Webull's "XYZ B" is the app's XYZ.B
    assert ids["FUND"][:2] == ("4", "etf")
    assert (
        db.query(Security).count() == 6
    )  # nothing added for symbols not in the master


def test_a_ticker_change_keeps_the_security_and_its_history(db, master, sec_off):
    master["AAA"].webull_id = "1"
    db.commit()
    webull = FakeWebull(
        pages={"COMMON_STOCK": [[{"symbol": "AAAX", "instrument_id": 1}]], "ETF": [[]]}
    )
    IdentifierService(db, webull).run(DAY)
    assert db.get(SecuritySymbol, master["AAA"].id).symbol == "AAAX"
    spans = sorted(
        (h.symbol, str(h.valid_to))
        for h in db.query(SecuritySymbolHist).filter_by(security_id=master["AAA"].id)
    )
    assert spans == [("AAA", str(DAY)), ("AAAX", "None")]


def test_sec_companies_codes_and_figis_are_filled_in(db, master, monkeypatch):
    monkeypatch.setattr(settings, "sec_contact_email", "research@example.com")
    monkeypatch.setattr("app.md.identifiers.time.sleep", lambda s: None)

    def sec(url):
        if url.endswith("company_tickers_exchange.json"):
            return {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [1111, "AAA CORP", "AAA", "Nasdaq"],
                    [2222, "XYZ HOLDINGS", "XYZ-B", "NYSE"],
                ],
            }
        return {
            "sic": "3674",
            "sicDescription": "Semiconductors & Related Devices",
            "fiscalYearEnd": "1231",
        }

    monkeypatch.setattr(sources, "sec", sec)
    monkeypatch.setattr(
        sources,
        "figi",
        lambda jobs: [
            {"data": [{"compositeFIGI": f"BBG{j['idValue'].replace('/', '')}"}]}
            if j["idValue"] != "CCC"
            else {"warning": "none"}
            for j in jobs
        ],
    )
    IdentifierService(db, FakeWebull()).run(DAY)

    aaa = master["AAA"]
    db.refresh(aaa)
    company = db.get(Company, aaa.company_id)
    assert (company.cik, company.sic_code, company.sic_description) == (
        "0000001111",
        "3674",
        "Semiconductors & Related Devices",
    )
    assert db.get(Security, master["XYZ.B"].id).company_id is not None  # SEC's XYZ-B
    figis = {
        sym: sec.figi
        for sym, sec in db.query(SecuritySymbol.symbol, Security).join(Security)
    }
    assert (
        figis["AAA"] == "BBGAAA"
        and figis["XYZ.B"] == "BBGXYZB"
        and figis["CCC"] is None
    )


def test_a_webull_refusal_stops_its_part_and_is_on_record(db, master, sec_off):
    IdentifierService(
        db, FakeWebull(pages={"COMMON_STOCK": [[], []]}, refuse_after=0)
    ).run(DAY)
    run = db.query(JobRun).filter_by(job="md_identifiers").one()
    assert run.outcome == "failed" and "refused" in run.note


# -- classification --------------------------------------------------------------


def test_sectors_and_industries_come_from_the_right_sources(db, master):
    ivv_file(
        db,
        [
            stock("AAA", "Information Technology"),
            stock("BBB", "Information Technology"),
            stock("CCC", "Financials"),
        ],
    )
    webull = FakeWebull(
        profiles={
            "AAA": ["Semiconductors & Equipment", "Semiconductors"],
            "BBB": ["Semiconductors & Equipment", "Semiconductors"],
            "CCC": ["Banking Services", "Banks"],
            "OFF": [
                "Semiconductors & Equipment",
                "Semiconductor Equipment",
            ],  # same group, other industry
            "XYZ B": [
                "Semiconductors & Equipment",
                "Semiconductors",
            ],  # not in the index
        }
    )
    ClassificationService(db, webull).run(DAY)

    assert now(db, "AAA") == ("IT", "Semiconductors", "ishares", "webull")
    assert now(db, "CCC") == ("FIN", "Banks", "ishares", "webull")
    # Not in the index: the sector its Webull industry's index members carry.
    assert now(db, "XYZ.B") == ("IT", "Semiconductors", "webull", "webull")
    # An industry with no index member has no sector yet, and says so.
    assert now(db, "OFF") == (None, "Semiconductor Equipment", None, "webull")
    assert (
        db.query(Industry).filter_by(name="Semiconductors").one().sector_basis
        == "ishares_majority"
    )
    assert now(db, "FUND") is None  # funds are not asked for a company profile


def test_a_stock_in_two_index_files_is_recorded_once(db, master):
    ivv_file(db, [stock("AAA", "Information Technology")])
    ivv_file(db, [stock("AAA", "Information Technology")], name="IWB")
    db.add(
        IndexDef(
            code="R1000",
            name="Russell 1000",
            owner="FTSE Russell",
            method="fund_file",
            source="ishares:IWB",
        )
    )
    db.commit()
    ClassificationService(db, FakeWebull(profiles={})).run(DAY)

    assert now(db, "AAA")[0] == "IT"
    assert db.query(SecurityClassificationHist).filter_by(source="ishares").count() == 1


def test_the_sec_code_is_the_fallback(db, master, monkeypatch):
    company = Company(
        name="OFF CORP",
        cik="0000003333",
        sic_code="6798",
        sic_description="Real Estate Investment Trusts",
    )
    db.add(company)
    db.flush()
    master["OFF"].company_id = company.id
    db.commit()
    ClassificationService(db, FakeWebull()).run(DAY)
    assert now(db, "OFF") == ("RE", "Real Estate Investment Trusts", "sec", "sec")
    assert (
        sic_sector("2834") == "HC"
        and sic_sector("7372") == "IT"
        and sic_sector("9999") is None
    )


def test_a_hand_entry_wins_and_survives_later_runs(db, master):
    ivv_file(db, [stock("AAA", "Information Technology"), stock("BBB"), stock("CCC")])
    service = ClassificationService(db, FakeWebull())
    service.run(DAY)
    service.set_manual("AAA", "COM", "Interactive Media", DAY)
    assert now(db, "AAA") == ("COM", "Interactive Media", "manual", "manual")
    ClassificationService(db, FakeWebull()).run(NEXT)
    assert now(db, "AAA")[:3] == ("COM", "Interactive Media", "manual")


def test_a_changed_view_closes_the_old_span(db, master):
    ivv_file(db, [stock("AAA", "Information Technology"), stock("BBB"), stock("CCC")])
    ClassificationService(db, FakeWebull()).run(DAY)
    ivv_file(
        db,
        [stock("AAA", "Communication"), stock("BBB"), stock("CCC")],
        as_of=date(2026, 10, 17),
    )
    ClassificationService(db, FakeWebull()).run(NEXT)
    spans = sorted(
        (h.sector_code, str(h.valid_from), str(h.valid_to))
        for h in db.query(SecurityClassificationHist).filter_by(
            security_id=master["AAA"].id, source="ishares"
        )
    )
    assert spans == [("COM", str(NEXT), "None"), ("IT", str(DAY), str(NEXT))]
    assert now(db, "AAA")[0] == "COM"


def test_running_twice_on_the_same_day_adds_nothing(db, master):
    ivv_file(db, [stock("AAA"), stock("BBB"), stock("CCC")])
    ClassificationService(db, FakeWebull()).run(DAY)
    before = db.query(SecurityClassificationHist).count()
    ClassificationService(db, FakeWebull()).run(DAY)
    assert db.query(SecurityClassificationHist).count() == before


def test_profiles_are_asked_once_and_a_refusal_stops_the_night(db, master):
    first = FakeWebull(profiles={"AAA": ["Banking Services", "Banks"]}, refuse_after=2)
    ClassificationService(db, first).run(DAY)
    run = (
        db.query(JobRun)
        .filter_by(job="md_classification")
        .order_by(JobRun.started_at.desc())
        .first()
    )
    assert run.outcome == "failed"
    second = FakeWebull()
    ClassificationService(db, second).run(DAY)
    # Two were asked before the refusal; the other three stocks are asked now.
    assert second.requests == 3


def test_a_profile_with_no_answer_is_asked_again(db, master):
    ClassificationService(db, FakeWebull(silent=("AAA",))).run(DAY)
    asked = {
        symbol
        for symbol, checked in db.query(
            SecuritySymbol.symbol, Security.profile_checked_at
        ).join(Security, Security.id == SecuritySymbol.security_id)
        if checked is not None
    }
    assert "AAA" not in asked and {"BBB", "CCC"} <= asked

    again = FakeWebull(profiles={"AAA": ["Banking Services", "Banks"]})
    ClassificationService(db, again).run(NEXT)
    assert again.requests == 1
    assert now(db, "AAA")[1] == "Banks"


def test_webull_not_answering_stops_the_profiles_but_not_the_job(db, master):
    ivv_file(db, [stock("AAA", "Information Technology")])
    silent = FakeWebull(silent=("*",))
    note = ClassificationService(db, silent).run(DAY)
    assert "not answering" in note
    assert silent.requests == 5  # all five stocks, the fifth failure stops it
    assert now(db, "AAA")[0] == "IT"  # the index files were still read


def test_a_webull_timeout_on_the_list_leaves_the_rest_of_the_job(
    db, master, sec_off, monkeypatch
):
    class Silent(FakeWebull):
        def get(self, path, query=None):
            self.requests += 1
            raise WebullUnreachable(path)

    reached = []
    monkeypatch.setattr(
        IdentifierService, "_sec_companies", lambda self: reached.append("sec")
    )
    note = IdentifierService(db, Silent()).run(DAY)
    assert "not read" in note and reached == ["sec"]


def test_a_security_known_only_by_its_ticker_is_named(db):
    from app.md.identifiers import fill_names
    from app.md.models import Company

    company = Company(name="EXAMPLE HOLDINGS CORP", cik="0000000001")
    db.add(company)
    db.flush()
    by_sec = Security(name="AAA", kind="stock", company_id=company.id)
    by_webull = Security(name="BBB", kind="etf")
    named_already = Security(name="Hand-set name", kind="stock", company_id=company.id)
    nameless = Security(name="CCC", kind="stock")
    db.add_all([by_sec, by_webull, named_already, nameless])
    db.flush()
    for security, symbol in (
        (by_sec, "AAA"),
        (by_webull, "BBB"),
        (named_already, "DDD"),
        (nameless, "CCC"),
    ):
        db.add(SecuritySymbol(security_id=security.id, symbol=symbol))
    db.flush()
    assert fill_names(db, {by_webull.id: "Example Fund Trust"}) == 2
    assert by_sec.name == "EXAMPLE HOLDINGS CORP"  # the SEC company's name first
    assert by_webull.name == "Example Fund Trust"
    assert named_already.name == "Hand-set name"  # never replaced
    assert nameless.name == "CCC"  # nothing to go on
    assert fill_names(db) == 0
