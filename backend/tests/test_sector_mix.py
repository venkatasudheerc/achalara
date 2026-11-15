# flake8: noqa: F811
"""Where holdings sit in the 11 sectors: the app's copy of market data's classification.

Every company, ticker and sector assignment here is invented.
"""
from datetime import date

import pytest

from app.md import read as md_read
from app.md.models import Sector, Security, SecurityClassification, SecuritySymbol
from app.md.sectors import SECTORS
from app.models.security_sector import SecuritySector
from app.services import sector_copy
from tests.test_portal import _trade, maya, world  # fixtures, used by name


@pytest.fixture
def market(db):
    """Market data knowing a stock with a sector, a fund, and a stock with none."""
    db.add_all([Sector(code=c, name=n, sort=o) for c, n, o in SECTORS])
    db.flush()
    made = {}
    for symbol, kind, sector in (
        ("AAPL", "stock", "IT"),
        ("VOO", "etf", None),
        ("XYZ", "stock", None),
    ):
        security = Security(name=f"{symbol} INC", kind=kind)
        db.add(security)
        db.flush()
        db.add(SecuritySymbol(security_id=security.id, symbol=symbol))
        db.add(SecurityClassification(security_id=security.id, sector_code=sector, as_of=date(2026, 11, 1)))
        made[symbol] = security
    db.commit()
    return made


def _held(db, world):
    # XYZ and QQQQ are held too; market data has no sector for XYZ and has never heard of QQQQ.
    _trade(db, world["brokerage_growth"], date(2026, 3, 2), "BUY", 5, 10, "XYZ")
    _trade(db, world["brokerage_growth"], date(2026, 3, 2), "BUY", 5, 10, "QQQQ")
    db.commit()


def test_the_copy_holds_each_held_symbols_sector_and_what_market_data_does_not_know(db, world, market):
    _held(db, world)
    changed = sector_copy.refresh(db)
    rows = {r.symbol: r for r in db.query(SecuritySector)}
    assert changed == len(rows)
    assert (rows["AAPL"].kind, rows["AAPL"].sector_code, rows["AAPL"].sector_name) == (
        "stock", "IT", "Information Technology"
    )
    assert (rows["VOO"].kind, rows["VOO"].sector_code) == ("etf", None)
    assert (rows["XYZ"].kind, rows["XYZ"].sector_code) == ("stock", None)
    # Never heard of: a row all the same, so "not classified" is on file.
    assert (rows["QQQQ"].kind, rows["QQQQ"].sector_code) == (None, None)


def test_refreshing_again_changes_nothing_and_a_new_sector_is_picked_up(db, world, market):
    _held(db, world)
    sector_copy.refresh(db)
    assert sector_copy.refresh(db) == 0
    xyz = db.query(SecurityClassification).filter_by(security_id=market["XYZ"].id).one()
    xyz.sector_code = "HC"
    db.commit()
    assert sector_copy.refresh(db) == 1
    assert db.get(SecuritySector, "XYZ").sector_code == "HC"


def test_market_data_out_of_reach_leaves_the_copy_as_it_was(db, world, market, monkeypatch):
    _held(db, world)
    sector_copy.refresh(db)

    def gone(*_args, **_kwargs):
        raise md_read.MdUnavailable("down")

    monkeypatch.setattr(md_read, "sectors_for", gone)
    assert sector_copy.refresh(db) == 0
    assert db.get(SecuritySector, "AAPL").sector_code == "IT"


def test_positions_say_where_each_holding_sits(maya, db, world, market):
    sector_copy.refresh(db)
    rows = {p["symbol"]: p for p in maya.get("/api/v1/portal/positions").json()["positions"]}
    assert (rows["AAPL"]["sector_group"], rows["AAPL"]["sector"], rows["AAPL"]["sector_code"]) == (
        "sector", "Information Technology", "IT"
    )
    # A fund has no sector and is not guessed at; the portal also reads a trade's own ETF type.
    assert (rows["VOO"]["sector_group"], rows["VOO"]["sector"]) == ("fund", None)
    assert rows["VTI"]["sector_group"] == "fund"  # unknown to market data, but typed ETF
    option = next(p for p in rows.values() if p["security_type"] == "option")
    assert (option["sector_group"], option["sector"]) == (None, None)


def test_a_stock_with_no_copy_row_is_unclassified_not_dropped(maya, world):
    rows = {p["symbol"]: p for p in maya.get("/api/v1/portal/positions").json()["positions"]}
    assert rows["AAPL"]["sector_group"] == "unclassified"
    assert rows["AAPL"]["sector"] is None


def test_a_client_sees_sectors_only_for_the_accounts_in_view(maya, db, world, market):
    sector_copy.refresh(db)
    rows = maya.get("/api/v1/portal/positions").json()["positions"]
    assert "JNJ" not in {p["symbol"] for p in rows}  # Ravi's trust: nothing leaks through the copy


def test_the_job_is_listed_on_system_status(client):
    ids = [j["id"] for j in client.get("/api/v1/admin/status").json()["jobs"]]
    assert "sector_copy" in ids
