"""The model holds any market; the feeds so far are American and stay so."""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.md import read as md_read
from app.md.classification import ClassificationService
from app.md.membership import MembershipService
from app.md.models import (
    Market,
    Security,
    SecurityClassification,
    SecuritySymbol,
    SecuritySymbolHist,
    US_MARKET,
)
from app.md.seed import seed_securities

TODAY = date(2026, 11, 5)
ABROAD = "XABC"  # an invented exchange's MIC


def _market(db):
    db.add(
        Market(
            code=ABROAD,
            name="Example Exchange",
            country="GB",
            currency="GBP",
            timezone="Europe/London",
            mic=ABROAD,
        )
    )
    db.flush()


def _security(db, symbol, market=US_MARKET, currency="USD"):
    security = Security(
        name=symbol, kind="stock", market_code=market, currency=currency
    )
    db.add(security)
    db.flush()
    db.add(SecuritySymbol(security_id=security.id, symbol=symbol, market_code=market))
    db.add(
        SecuritySymbolHist(
            security_id=security.id,
            symbol=symbol,
            market_code=market,
            valid_from=TODAY,
            source="test",
        )
    )
    db.flush()
    return security


def test_a_security_is_american_unless_told_otherwise(db):
    security = Security(name="Example", kind="stock")
    db.add(security)
    db.flush()
    link = SecuritySymbol(security_id=security.id, symbol="AAA")
    db.add(link)
    db.flush()
    assert (security.market_code, security.currency) == ("US", "USD")
    assert link.market_code == "US"


def test_one_ticker_can_mean_different_securities_in_different_markets(db):
    _market(db)
    american = _security(db, "AAA")
    foreign = _security(db, "AAA", market=ABROAD, currency="GBP")
    assert american.id != foreign.id
    assert foreign.currency == "GBP"


def test_one_ticker_means_one_security_within_a_market(db):
    _security(db, "AAA")
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            _security(db, "AAA")


def test_tickers_a_foreign_exchange_uses_fit(db):
    _market(db)
    for symbol in ("0700", "LONGTICKER", "ABC.XY"):
        assert _security(db, symbol, market=ABROAD).id


def test_a_share_class_may_be_shared_across_markets(db):
    _market(db)
    for market, figi in ((US_MARKET, "BBG000000001"), (ABROAD, "BBG000000002")):
        security = _security(db, "AAA", market=market)
        security.figi = figi
        security.share_class_figi = "BBG00000000X"
        security.isin = "XX0000000000"
    db.flush()
    assert db.query(Security).filter(Security.isin == "XX0000000000").count() == 2


def test_seeding_is_not_confused_by_the_same_ticker_abroad(db):
    _market(db)
    _security(db, "AAA", market=ABROAD)
    assert seed_securities(db, [("AAA", "STOCK")], TODAY) == 1
    american = db.query(SecuritySymbol).filter_by(symbol="AAA", market_code="US").one()
    assert american.security_id
    assert seed_securities(db, [("AAA", "STOCK")], TODAY) == 0


def test_the_sector_warning_counts_only_the_american_line(db):
    _market(db)
    _security(db, "AAA", market=ABROAD)
    american = _security(db, "AAA")
    db.add(
        SecurityClassification(security_id=american.id, sector_code="IT", as_of=TODAY)
    )
    db.flush()
    assert md_read.stocks_without_sector(db, ["AAA"]) == 0


def test_index_files_match_american_lines_only(db):
    _market(db)
    foreign = _security(db, "AAA", market=ABROAD)
    from app.md.readers import Holding

    service = MembershipService(db)
    holding = Holding(
        symbol="AAA", name="Example", kind="stock", sector=None, exchange=None, weight=1
    )
    found = service._security_for(holding, TODAY, "ishares")
    assert found.id != foreign.id
    assert found.market_code == "US"


def test_a_hand_set_sector_lands_on_the_american_line(db):
    _market(db)
    _security(db, "AAA", market=ABROAD)
    american = _security(db, "AAA")
    ClassificationService(db).set_manual("AAA", "IT", None, TODAY)
    classified = db.query(SecurityClassification).one()
    assert classified.security_id == american.id
