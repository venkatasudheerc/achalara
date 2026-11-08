"""Market data: index membership from fund holdings files. Invented securities only."""
import gzip
import io
import zipfile
from datetime import date

import pytest

from app.md import sources
from app.md.membership import JOB, run_index_membership
from app.md.models import (
    IndexDef,
    IndexMember,
    IndexMemberHist,
    JobRun,
    Security,
    SecuritySymbol,
    SourceFile,
)
from app.md.readers import read_ishares_csv, read_ssga_xlsx
from app.md.seed import seed_securities
from app.services.held_symbols import held_symbols

HEADER = (
    "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,"
    "Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date"
)


def ishares_csv(as_of: str, lines) -> bytes:
    """An iShares holdings file: fund details, a blank line, then the table."""
    rows = [
        "iShares Example Fund",
        f'Fund Holdings as of,"{as_of}"',
        'Inception Date,"May 15, 2000"',
        "",
        HEADER,
    ]
    for ticker, name, sector, asset in lines:
        rows.append(
            f'"{ticker}","{name}","{sector}","{asset}","1,000.00","1.00","1,000.00","10.00","100.00",'
            '"United States","NASDAQ","USD","1.00","USD","-"'
        )
    return "\n".join(rows).encode()


def stock(ticker, sector="Information Technology"):
    return (ticker, f"{ticker} INC", sector, "Equity")


def ssga_xlsx(as_of: str, tickers) -> bytes:
    """A State Street holdings workbook with inline strings (no shared strings)."""

    def cell(ref, value):
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'

    rows = (
        [
            ["Fund Name:", "Example Fund"],
            ["Holdings:", f"As of {as_of}"],
            [
                "Name",
                "Ticker",
                "Identifier",
                "SEDOL",
                "Weight",
                "Sector",
                "Shares Held",
                "Local Currency",
            ],
        ]
        + [[f"{t} INC", t, f"ID{t}", "123", "1.0", "-", "10", "USD"] for t in tickers]
        + [
            ["US DOLLAR", "-", "999USD", "", "0.1", "-", "1", "USD"],
        ]
    )
    xml_rows = "".join(
        f'<row r="{i + 1}">'
        + "".join(cell(f"{chr(65 + j)}{i + 1}", v) for j, v in enumerate(r))
        + "</row>"
        for i, r in enumerate(rows)
    )
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{xml_rows}</sheetData></worksheet>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


@pytest.fixture
def indices(db):
    """The four indices, with member ranges sized for these small files."""
    db.add_all(
        [
            IndexDef(
                code="SP500",
                name="S&P 500",
                owner="S&P",
                method="fund_file",
                source="ishares:IVV",
                expected_min=2,
                expected_max=10,
            ),
            IndexDef(
                code="R1000",
                name="Russell 1000",
                owner="FTSE Russell",
                method="fund_file",
                source="ishares:IWB",
                expected_min=2,
                expected_max=10,
            ),
            IndexDef(
                code="R2000",
                name="Russell 2000",
                owner="FTSE Russell",
                method="fund_file",
                source="ishares:IWM",
                expected_min=2,
                expected_max=10,
            ),
            IndexDef(
                code="R3000",
                name="Russell 3000",
                owner="FTSE Russell",
                method="union",
                parts="R1000,R2000",
                expected_min=4,
                expected_max=20,
            ),
        ]
    )
    db.commit()


@pytest.fixture
def files(monkeypatch):
    """The files the funds 'publish'; tests change them between runs."""
    published = {
        "IVV": ishares_csv(
            "Oct 15, 2026",
            [
                stock("AAA"),
                stock("BBB"),
                stock("CCC", "Financials"),
                ("XYZ WS", "XYZ WARRANT", "Industrials", "Equity"),
                ("USD", "USD CASH", "Cash and/or Derivatives", "Cash"),
                ("ESZ6", "S&P500 EMINI DEC 26", "Cash and/or Derivatives", "Futures"),
            ],
        ),
        "IWB": ishares_csv(
            "Oct 15, 2026", [stock("AAA"), stock("BBB"), stock("CCC"), stock("DDD")]
        ),
        "IWM": ishares_csv(
            "Oct 15, 2026",
            [
                stock("EEE"),
                stock("FFF"),
                ("-", "UNNAMED RIGHT", "Health Care", "Equity"),
                ("GGG B", "GGG CLASS B", "Industrials", "Equity"),
            ],
        ),
        "SPY": ssga_xlsx("15-Oct-2026", ["AAA", "BBB", "CCC"]),
    }
    by_url = {sources.FUND_FILES[name].url: name for name in published}
    monkeypatch.setattr(sources, "fetch", lambda url: published[by_url[url]])
    return published


def members(db, code):
    return sorted(
        row[0]
        for row in db.query(SecuritySymbol.symbol)
        .join(IndexMember, IndexMember.security_id == SecuritySymbol.security_id)
        .filter(IndexMember.index_code == code)
    )


def test_readers_keep_securities_and_write_the_apps_spelling(files):
    as_of, rows = read_ishares_csv(files["IVV"])
    assert as_of == date(2026, 10, 15)
    assert [(r.symbol, r.kind) for r in rows] == [
        ("AAA", "stock"),
        ("BBB", "stock"),
        ("CCC", "stock"),
        ("XYZ.WS", "other"),
    ]
    assert rows[2].sector == "Financials"

    _, rows = read_ishares_csv(files["IWM"])
    assert [r.symbol for r in rows] == ["EEE", "FFF", "GGG.B"]  # no-ticker line dropped

    as_of, rows = read_ssga_xlsx(files["SPY"])
    assert as_of == date(2026, 10, 15)
    assert [r.symbol for r in rows] == ["AAA", "BBB", "CCC"]  # cash line dropped


def test_a_first_run_fills_every_index_and_keeps_each_file(db, indices, files):
    outcome = run_index_membership(db)

    assert outcome.refused == {} and outcome.check is None
    assert members(db, "SP500") == ["AAA", "BBB", "CCC"]  # the warrant is not a member
    assert members(db, "R2000") == ["EEE", "FFF", "GGG.B"]
    assert members(db, "R3000") == ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG.B"]
    assert db.query(Security).count() == 7  # the warrant is not added at all

    stored = {(f.source, f.name): f for f in db.query(SourceFile)}
    assert set(stored) == {
        ("ishares", "IVV"),
        ("ishares", "IWB"),
        ("ishares", "IWM"),
        ("ssga", "SPY"),
    }
    assert gzip.decompress(stored[("ishares", "IVV")].content) == files["IVV"]

    (run,) = db.query(JobRun).filter(JobRun.job == JOB).all()
    assert run.outcome == "ok" and run.requests == 4


def test_a_ticker_a_file_lists_twice_is_one_security(db, indices, files):
    """A fund file can list one ticker on two lines (two lots, or two spellings of a
    share class). It is one security, and the run must not fail on it."""
    files["IWM"] = ishares_csv(
        "Oct 15, 2026",
        [
            stock("EEE"),
            stock("EEE"),
            stock("FFF"),
            ("GGG B", "GGG CLASS B", "Industrials", "Equity"),
            ("GGG.B", "GGG CLASS B", "Industrials", "Equity"),
        ],
    )
    outcome = run_index_membership(db)

    assert outcome.refused == {}
    assert members(db, "R2000") == ["EEE", "FFF", "GGG.B"]
    assert db.query(SecuritySymbol).filter(SecuritySymbol.symbol == "EEE").count() == 1
    assert db.query(Security).count() == 7
    (run,) = db.query(JobRun).filter(JobRun.job == JOB).all()
    assert run.outcome == "ok"


def test_a_later_file_closes_leavers_and_opens_joiners(db, indices, files):
    run_index_membership(db)
    files["IVV"] = ishares_csv(
        "Oct 16, 2026", [stock("AAA"), stock("BBB"), stock("DDD")]
    )
    files["SPY"] = ssga_xlsx("16-Oct-2026", ["AAA", "BBB", "DDD"])

    run_index_membership(db)

    assert members(db, "SP500") == ["AAA", "BBB", "DDD"]
    spans = {
        (sym, str(h.valid_from), str(h.valid_to))
        for h, sym in db.query(IndexMemberHist, SecuritySymbol.symbol)
        .join(SecuritySymbol, SecuritySymbol.security_id == IndexMemberHist.security_id)
        .filter(IndexMemberHist.index_code == "SP500")
    }
    assert (
        "CCC",
        "2026-10-15",
        "2026-10-16",
    ) in spans  # left: the span ends the day it is gone
    assert ("DDD", "2026-10-16", "None") in spans  # joined
    assert ("AAA", "2026-10-15", "None") in spans  # unchanged spans stay open


def test_running_twice_on_the_same_files_changes_nothing(db, indices, files):
    run_index_membership(db)
    before = (
        db.query(IndexMemberHist).count(),
        db.query(SourceFile).count(),
        db.query(Security).count(),
    )
    outcome = run_index_membership(db)
    assert all(joined == left == 0 for _, _, joined, left in outcome.applied.values())
    assert (
        db.query(IndexMemberHist).count(),
        db.query(SourceFile).count(),
        db.query(Security).count(),
    ) == before


def test_a_file_with_too_few_members_is_not_applied(db, indices, files):
    run_index_membership(db)
    files["IVV"] = ishares_csv("Oct 16, 2026", [stock("AAA")])  # truncated download

    outcome = run_index_membership(db)

    assert "SP500" in outcome.refused
    assert members(db, "SP500") == ["AAA", "BBB", "CCC"]
    last = db.query(JobRun).order_by(JobRun.started_at.desc()).first()
    assert last.outcome == "failed" and "SP500 not applied" in last.note


def test_an_older_file_never_rolls_membership_back(db, indices, files):
    files["IVV"] = ishares_csv(
        "Oct 16, 2026", [stock("AAA"), stock("BBB"), stock("CCC")]
    )
    run_index_membership(db)
    files["IVV"] = ishares_csv(
        "Oct 15, 2026", [stock("AAA"), stock("BBB"), stock("ZZZ")]
    )
    outcome = run_index_membership(db)
    assert "older" in outcome.refused["SP500"]
    assert members(db, "SP500") == ["AAA", "BBB", "CCC"]


def test_the_russell_3000_waits_for_both_parts(db, indices, files):
    files["IWM"] = b"not a holdings file"
    outcome = run_index_membership(db)
    assert set(outcome.refused) == {"R2000", "R3000"}
    assert members(db, "R3000") == []


def test_state_street_disagreeing_is_reported_not_applied(db, indices, files):
    files["SPY"] = ssga_xlsx("15-Oct-2026", ["AAA", "BBB", "QQQQ"])
    outcome = run_index_membership(db)
    assert (
        "only iShares ['CCC']" in outcome.check
        and "only State Street ['QQQQ']" in outcome.check
    )
    assert members(db, "SP500") == ["AAA", "BBB", "CCC"]


def test_held_securities_are_added_once_options_left_out(db):
    from app.models.account import Account
    from app.models.client import Client
    from app.models.sleeve import Sleeve
    from app.models.strategy import Strategy
    from app.models.trade import Trade

    client = Client(name="Test Client", email="md-seed@example.com")
    strategy = Strategy(name="Seed test")
    db.add_all([client, strategy])
    db.flush()
    account = Account(client_id=client.id, name="Test account")
    db.add(account)
    db.flush()
    sleeve = Sleeve(account_id=account.id, strategy_id=strategy.id)
    db.add(sleeve)
    db.flush()
    for symbol, kind in (
        ("AAA", "STOCK"),
        ("ETFX", "ETF"),
        ("NASDAQ:BBB", "STOCK"),
        ("AAA261218C00100000", "OPTION"),
        ("FNDX", "MUTUAL_FUND"),
        ("~EXAMPLE HOLDINGS INC", "STOCK"),  # a brokerage placeholder, not a ticker
    ):
        db.add(
            Trade(
                sleeve_id=sleeve.id,
                trade_date=date(2026, 10, 1),
                symbol=symbol,
                action="BUY",
                quantity=1,
                price=10,
                security_type=kind,
            )
        )
    db.commit()

    assert seed_securities(db, held_symbols(db), date(2026, 10, 18)) == 4
    kinds = {
        sym: kind
        for sym, kind in db.query(SecuritySymbol.symbol, Security.kind).join(Security)
    }
    assert kinds == {"AAA": "stock", "BBB": "stock", "ETFX": "etf", "FNDX": "fund"}
    assert seed_securities(db, held_symbols(db), date(2026, 10, 18)) == 0


def test_system_status_lists_market_data_jobs_and_a_failure(client, db, indices, files):
    files["IVV"] = ishares_csv("Oct 15, 2026", [stock("AAA")])
    run_index_membership(db)

    body = client.get("/api/v1/admin/status").json()
    jobs = {j["id"]: j for j in body["jobs"]}
    assert jobs["md_index_membership"]["last_ok"] is False
    assert jobs["md_index_membership"]["next_run_at"] is not None
    assert "Market data: index membership failed on its last run." in body["attention"]


def test_a_run_left_running_by_a_stopped_process_is_closed(db):
    from datetime import datetime, timezone

    from app.md.jobs import close_abandoned

    started = datetime(2026, 11, 7, 21, 0, tzinfo=timezone.utc)
    db.add_all(
        [
            JobRun(job="md_identifiers", started_at=started, outcome="running"),
            JobRun(job="md_identifiers", started_at=started, outcome="ok"),
        ]
    )
    db.commit()
    assert close_abandoned(db) == 1
    outcomes = sorted(r.outcome for r in db.query(JobRun))
    assert outcomes == ["failed", "ok"]
    closed = db.query(JobRun).filter(JobRun.outcome == "failed").one()
    assert closed.note.startswith("Interrupted") and closed.finished_at is not None
    assert close_abandoned(db) == 0
