"""Market-data models — the ``md`` schema.

Two kinds of table, kept apart on purpose:

- **Current** tables hold one row per thing (a security, its ticker today, an
  index's members today). They stay small and are what screens join to.
- **History** tables (suffix ``_hist``) hold dated rows, keyed by the thing and
  the date. Every current table can be rebuilt from its history table, and a
  loader writes both in the same transaction.

Operations tables record every file fetched and every job run.
"""
import uuid

from sqlalchemy import (
    Index,
    BigInteger,
    Numeric,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)

from app.md.base import MdModel

SCHEMA = "md"
# Every feed so far is American. Other markets are rows in ``md.market``.
US_MARKET = "US"
US_CURRENCY = "USD"


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Current
# ---------------------------------------------------------------------------


class Market(MdModel):
    """Where a ticker means one thing: the US as a whole, or one foreign exchange.

    American exchanges share one set of tickers, so they are one market. Abroad
    each exchange has its own, so each is a market, coded by its MIC (``XLON``).
    """

    __tablename__ = "market"
    __table_args__ = {"schema": SCHEMA}

    code = Column(String(12), primary_key=True)
    name = Column(String(80), nullable=False)
    country = Column(String(2), nullable=False)  # ISO 3166
    currency = Column(String(3), nullable=False)  # ISO 4217, the usual one there
    timezone = Column(String(40), nullable=False)  # IANA, e.g. America/New_York
    mic = Column(String(4))  # ISO 10383; empty for a market of several exchanges


class Company(MdModel):
    """A legal company. Fundamentals hang off this; GOOG and GOOGL share one."""

    __tablename__ = "company"
    __table_args__ = {"schema": SCHEMA}

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    cik = Column(String(10), unique=True)  # SEC id; empty for issuers without one
    sic_code = Column(String(4))
    sic_description = Column(String(120))
    fiscal_year_end = Column(String(4))  # MMDD
    country = Column(String(60))


class Security(MdModel):
    """A tradable line: a share class, an ETF, an ADR, a fund."""

    __tablename__ = "security"
    __table_args__ = {"schema": SCHEMA}

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey(f"{SCHEMA}.company.id"))
    # One market: the same company listed elsewhere is another security.
    market_code = Column(
        String(12),
        ForeignKey(f"{SCHEMA}.market.code"),
        nullable=False,
        default=US_MARKET,
        index=True,
    )
    currency = Column(String(3), nullable=False, default=US_CURRENCY)  # as quoted
    name = Column(String(255), nullable=False)
    # stock | etf | adr | fund | preferred | other
    kind = Column(String(20), nullable=False, default="stock")
    exchange = Column(String(60))
    figi = Column(String(12), unique=True)  # composite FIGI, the permanent id
    # These two follow a share class across markets, so neither is unique.
    share_class_figi = Column(String(12), index=True)
    isin = Column(String(12), index=True)
    webull_id = Column(String(30), unique=True)
    status = Column(String(12), nullable=False, default="active")  # active | delisted
    listed_from = Column(Date)
    delisted_on = Column(Date)
    # When Webull's company profile (industry) was last asked for.
    profile_checked_at = Column(DateTime(timezone=True))


class SecuritySymbol(MdModel):
    """The ticker a security uses today: the lookup from a symbol to its security."""

    __tablename__ = "security_symbol"
    __table_args__ = (
        UniqueConstraint(
            "market_code", "symbol", name="uq_md_security_symbol_market_symbol"
        ),
        {"schema": SCHEMA},
    )

    security_id = Column(
        String(36),
        ForeignKey(f"{SCHEMA}.security.id", ondelete="CASCADE"),
        primary_key=True,
    )
    symbol = Column(String(30), nullable=False)  # in the app's spelling
    market_code = Column(
        String(12),
        ForeignKey(f"{SCHEMA}.market.code"),
        nullable=False,
        default=US_MARKET,
    )


class Sector(MdModel):
    """One of the 11 GICS sectors."""

    __tablename__ = "sector"
    __table_args__ = {"schema": SCHEMA}

    code = Column(String(4), primary_key=True)  # IT, HC, FIN, …
    name = Column(String(40), nullable=False)
    sort = Column(Integer, nullable=False)


class Industry(MdModel):
    """An industry as a source names it, placed under one of the 11 sectors."""

    __tablename__ = "industry"

    id = Column(String(36), primary_key=True, default=_uuid)
    scheme = Column(String(12), nullable=False)  # webull | sec
    name = Column(String(120), nullable=False)
    industry_group = Column(
        String(120)
    )  # Webull's first level, e.g. "Banking Services"
    source_code = Column(String(10))  # SIC code for scheme sec
    sector_code = Column(String(4), ForeignKey(f"{SCHEMA}.sector.code"))
    # How the sector was decided: ishares_majority (most index members in this
    # industry carry that GICS sector), sic_map, or manual (never recomputed).
    sector_basis = Column(String(20))

    __table_args__ = (
        UniqueConstraint("scheme", "name", name="uq_md_industry_scheme_name"),
        {"schema": SCHEMA},
    )


class SecurityClassification(MdModel):
    """The sector and industry a security has now, and which source set each."""

    __tablename__ = "security_classification"
    __table_args__ = {"schema": SCHEMA}

    security_id = Column(
        String(36),
        ForeignKey(f"{SCHEMA}.security.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sector_code = Column(String(4), ForeignKey(f"{SCHEMA}.sector.code"))
    industry_id = Column(String(36), ForeignKey(f"{SCHEMA}.industry.id"))
    sector_source = Column(String(12))
    industry_source = Column(String(12))
    as_of = Column(Date, nullable=False)


class IndexDef(MdModel):
    """An index tracked, and how its membership is obtained."""

    __tablename__ = "index_def"
    __table_args__ = {"schema": SCHEMA}

    code = Column(String(12), primary_key=True)  # SP500 | R1000 | R2000 | R3000
    name = Column(String(80), nullable=False)
    owner = Column(String(60), nullable=False)
    # fund_file (a fund's daily holdings) | official_list | union (of other indices)
    method = Column(String(20), nullable=False)
    source = Column(String(30))  # e.g. ishares:IVV
    parts = Column(String(80))  # for union: comma-separated index codes
    expected_min = Column(Integer)
    expected_max = Column(Integer)
    level_symbol = Column(String(12))  # its own level in index history (SPX, …)


class IndexMember(MdModel):
    """A security in an index today."""

    __tablename__ = "index_member"
    __table_args__ = {"schema": SCHEMA}

    index_code = Column(
        String(12), ForeignKey(f"{SCHEMA}.index_def.code"), primary_key=True
    )
    security_id = Column(
        String(36),
        ForeignKey(f"{SCHEMA}.security.id", ondelete="CASCADE"),
        primary_key=True,
    )
    since = Column(Date, nullable=False)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class SecuritySymbolHist(MdModel):
    """Every ticker a security has used, and the source's own spelling of it."""

    __tablename__ = "security_symbol_hist"

    security_id = Column(
        String(36),
        ForeignKey(f"{SCHEMA}.security.id", ondelete="CASCADE"),
        primary_key=True,
    )
    symbol = Column(String(30), nullable=False, index=True)
    market_code = Column(
        String(12),
        ForeignKey(f"{SCHEMA}.market.code"),
        nullable=False,
        default=US_MARKET,
    )
    valid_from = Column(Date, primary_key=True)
    valid_to = Column(Date)  # empty while current
    source = Column(String(30), nullable=False)

    __table_args__ = ({"schema": SCHEMA},)


class SecurityClassificationHist(MdModel):
    """What one source said a security's sector and industry were, over a span."""

    __tablename__ = "security_classification_hist"

    security_id = Column(
        String(36),
        ForeignKey(f"{SCHEMA}.security.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source = Column(String(12), primary_key=True)  # ishares | webull | sec | manual
    valid_from = Column(Date, primary_key=True)
    valid_to = Column(Date)  # empty while current
    sector_code = Column(String(4), ForeignKey(f"{SCHEMA}.sector.code"))
    industry_id = Column(String(36), ForeignKey(f"{SCHEMA}.industry.id"))
    raw_sector = Column(String(120))  # the source's own words
    raw_industry = Column(String(240))
    raw_code = Column(String(10))

    __table_args__ = ({"schema": SCHEMA},)


class IndexMemberHist(MdModel):
    """One span of a security's membership of an index."""

    __tablename__ = "index_member_hist"

    index_code = Column(
        String(12), ForeignKey(f"{SCHEMA}.index_def.code"), primary_key=True
    )
    security_id = Column(
        String(36),
        ForeignKey(f"{SCHEMA}.security.id", ondelete="CASCADE"),
        primary_key=True,
    )
    valid_from = Column(Date, primary_key=True)
    valid_to = Column(Date)  # empty while a member
    source_file_id = Column(String(36), ForeignKey(f"{SCHEMA}.source_file.id"))

    __table_args__ = ({"schema": SCHEMA},)


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


class SourceFile(MdModel):
    """A file exactly as downloaded, so it can be read again if a reader was wrong."""

    __tablename__ = "source_file"

    id = Column(String(36), primary_key=True, default=_uuid)
    source = Column(String(30), nullable=False)  # ishares | ssga | …
    name = Column(String(30), nullable=False)  # the fund or list, e.g. IVV
    as_of = Column(Date, nullable=False)  # the date the file describes
    content = Column(LargeBinary, nullable=False)  # gzip-compressed
    sha256 = Column(String(64), nullable=False)
    rows = Column(Integer)
    fetched_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "name", "as_of", name="uq_md_source_file"),
        {"schema": SCHEMA},
    )


class JobRun(MdModel):
    """One run of a market-data job: the lasting record System status reads."""

    __tablename__ = "job_run"

    id = Column(String(36), primary_key=True, default=_uuid)
    job = Column(String(40), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    outcome = Column(
        String(12), nullable=False, default="running"
    )  # ok | failed | skipped
    requests = Column(Integer, nullable=False, default=0)
    rows_written = Column(Integer, nullable=False, default=0)
    note = Column(Text)  # what happened, or the error

    __table_args__ = ({"schema": SCHEMA},)


class TrackedFund(MdModel):
    """A fund priced alongside the index members (index members are all stocks).

    A row stays when a fund stops being tracked, and so do its prices.
    """

    __tablename__ = "tracked_fund"
    __table_args__ = {"schema": SCHEMA}

    security_id = Column(
        String(36),
        ForeignKey(f"{SCHEMA}.security.id", ondelete="CASCADE"),
        primary_key=True,
    )
    asset_group = Column(String(30), nullable=False)  # benchmark, sector, gold, …
    added_on = Column(Date, nullable=False)
    removed_on = Column(Date)  # empty while tracked
    note = Column(String(200))


class PriceDailyHist(MdModel):
    """One security's prices for one market day, as traded: not adjusted.

    Captured each evening from the day's snapshot, because no source gives past
    unadjusted prices back. A day on file is never overwritten.
    """

    __tablename__ = "price_daily_hist"
    __table_args__ = (
        Index("ix_md_price_daily_hist_price_date", "price_date"),
        {"schema": SCHEMA},
    )

    security_id = Column(
        String(36),
        ForeignKey(f"{SCHEMA}.security.id", ondelete="CASCADE"),
        primary_key=True,
    )
    price_date = Column(Date, primary_key=True)  # the market day
    currency = Column(String(3), nullable=False)
    open = Column(Numeric(18, 6))
    high = Column(Numeric(18, 6))
    low = Column(Numeric(18, 6))
    close = Column(Numeric(18, 6), nullable=False)
    volume = Column(BigInteger)
    last_trade_at = Column(DateTime(timezone=True))
    source = Column(String(20), nullable=False)  # webull_snapshot


class PriceAdjDaily(MdModel):
    """One security's close for one market day, adjusted for later splits and
    dividends: the series every return is computed from (a total return).

    Webull rewrites its whole adjusted series after each split or dividend, so
    these rows are refreshed and rescaled, never treated as fixed. Prices as
    traded are in ``price_daily_hist``.
    """

    __tablename__ = "price_adj_daily"
    __table_args__ = (
        Index("ix_md_price_adj_daily_price_date", "price_date"),
        {"schema": SCHEMA},
    )

    security_id = Column(
        String(36),
        ForeignKey(f"{SCHEMA}.security.id", ondelete="CASCADE"),
        primary_key=True,
    )
    price_date = Column(Date, primary_key=True)
    adj_close = Column(Numeric(18, 6), nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False)


class IndexLevelHist(MdModel):
    """A market index's closing level for one market day: a price return (no
    dividends). Linked from ``index_def.level_symbol``."""

    __tablename__ = "index_level_hist"
    __table_args__ = {"schema": SCHEMA}

    symbol = Column(String(12), primary_key=True)  # SPX, NDX, DJI, RUI, RUT, RUA
    price_date = Column(Date, primary_key=True)
    close = Column(Numeric(18, 4), nullable=False)
    source = Column(String(20), nullable=False)  # yahoo
    fetched_at = Column(DateTime(timezone=True), nullable=False)
