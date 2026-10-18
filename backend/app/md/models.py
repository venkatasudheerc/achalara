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

from app.models.base import BaseModel

SCHEMA = "md"


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Current
# ---------------------------------------------------------------------------


class Company(BaseModel):
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


class Security(BaseModel):
    """A tradable line: a share class, an ETF, an ADR, a fund."""

    __tablename__ = "security"
    __table_args__ = {"schema": SCHEMA}

    id = Column(String(36), primary_key=True, default=_uuid)
    company_id = Column(String(36), ForeignKey(f"{SCHEMA}.company.id"))
    name = Column(String(255), nullable=False)
    # stock | etf | adr | fund | preferred | other
    kind = Column(String(20), nullable=False, default="stock")
    exchange = Column(String(60))
    figi = Column(String(12), unique=True)  # composite FIGI, the permanent id
    webull_id = Column(String(30), unique=True)
    status = Column(String(12), nullable=False, default="active")  # active | delisted
    listed_from = Column(Date)
    delisted_on = Column(Date)
    # When Webull's company profile (industry) was last asked for.
    profile_checked_at = Column(DateTime(timezone=True))


class SecuritySymbol(BaseModel):
    """The ticker a security uses today: the lookup from a symbol to its security."""

    __tablename__ = "security_symbol"
    __table_args__ = {"schema": SCHEMA}

    security_id = Column(
        String(36),
        ForeignKey(f"{SCHEMA}.security.id", ondelete="CASCADE"),
        primary_key=True,
    )
    symbol = Column(String(30), nullable=False, unique=True)  # in the app's spelling


class Sector(BaseModel):
    """One of the 11 GICS sectors."""

    __tablename__ = "sector"
    __table_args__ = {"schema": SCHEMA}

    code = Column(String(4), primary_key=True)  # IT, HC, FIN, …
    name = Column(String(40), nullable=False)
    sort = Column(Integer, nullable=False)


class Industry(BaseModel):
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


class SecurityClassification(BaseModel):
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


class IndexDef(BaseModel):
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


class IndexMember(BaseModel):
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


class SecuritySymbolHist(BaseModel):
    """Every ticker a security has used, and the source's own spelling of it."""

    __tablename__ = "security_symbol_hist"

    security_id = Column(
        String(36),
        ForeignKey(f"{SCHEMA}.security.id", ondelete="CASCADE"),
        primary_key=True,
    )
    symbol = Column(String(30), nullable=False, index=True)
    valid_from = Column(Date, primary_key=True)
    valid_to = Column(Date)  # empty while current
    source = Column(String(30), nullable=False)

    __table_args__ = ({"schema": SCHEMA},)


class SecurityClassificationHist(BaseModel):
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


class IndexMemberHist(BaseModel):
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


class SourceFile(BaseModel):
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


class JobRun(BaseModel):
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
