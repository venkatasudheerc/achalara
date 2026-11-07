"""add md schema: securities and index membership

Revision ID: a5c1e9d27f40
Revises:
Create Date: 2026-10-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a5c1e9d27f40"
down_revision = None
branch_labels = None
depends_on = None

S = "md"


def _times():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS md")

    op.create_table(
        "company",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("cik", sa.String(10), unique=True),
        sa.Column("sic_code", sa.String(4)),
        sa.Column("fiscal_year_end", sa.String(4)),
        sa.Column("country", sa.String(60)),
        *_times(),
        schema=S,
    )
    op.create_table(
        "security",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), sa.ForeignKey("md.company.id")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("exchange", sa.String(60)),
        sa.Column("figi", sa.String(12), unique=True),
        sa.Column("webull_id", sa.String(30), unique=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("listed_from", sa.Date()),
        sa.Column("delisted_on", sa.Date()),
        *_times(),
        schema=S,
    )
    op.create_table(
        "security_symbol",
        sa.Column(
            "security_id",
            sa.String(36),
            sa.ForeignKey("md.security.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("symbol", sa.String(30), nullable=False, unique=True),
        *_times(),
        schema=S,
    )
    op.create_table(
        "index_def",
        sa.Column("code", sa.String(12), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("owner", sa.String(60), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("source", sa.String(30)),
        sa.Column("parts", sa.String(80)),
        sa.Column("expected_min", sa.Integer()),
        sa.Column("expected_max", sa.Integer()),
        sa.Column("level_symbol", sa.String(12)),
        *_times(),
        schema=S,
    )
    op.create_table(
        "source_file",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("name", sa.String(30), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("rows", sa.Integer()),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        *_times(),
        sa.UniqueConstraint("source", "name", "as_of", name="uq_md_source_file"),
        schema=S,
    )
    op.create_table(
        "index_member",
        sa.Column(
            "index_code",
            sa.String(12),
            sa.ForeignKey("md.index_def.code"),
            primary_key=True,
        ),
        sa.Column(
            "security_id",
            sa.String(36),
            sa.ForeignKey("md.security.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("since", sa.Date(), nullable=False),
        *_times(),
        schema=S,
    )
    op.create_table(
        "security_symbol_hist",
        sa.Column(
            "security_id",
            sa.String(36),
            sa.ForeignKey("md.security.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("symbol", sa.String(30), nullable=False),
        sa.Column("valid_from", sa.Date(), primary_key=True),
        sa.Column("valid_to", sa.Date()),
        sa.Column("source", sa.String(30), nullable=False),
        *_times(),
        schema=S,
    )
    op.create_index(
        "ix_md_security_symbol_hist_symbol",
        "security_symbol_hist",
        ["symbol"],
        schema=S,
    )
    op.create_table(
        "index_member_hist",
        sa.Column(
            "index_code",
            sa.String(12),
            sa.ForeignKey("md.index_def.code"),
            primary_key=True,
        ),
        sa.Column(
            "security_id",
            sa.String(36),
            sa.ForeignKey("md.security.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("valid_from", sa.Date(), primary_key=True),
        sa.Column("valid_to", sa.Date()),
        sa.Column("source_file_id", sa.String(36), sa.ForeignKey("md.source_file.id")),
        *_times(),
        schema=S,
    )
    op.create_table(
        "job_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String(12), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text()),
        *_times(),
        schema=S,
    )
    op.create_index("ix_md_job_run_job", "job_run", ["job"], schema=S)

    index_def = sa.table(
        "index_def",
        sa.column("code"),
        sa.column("name"),
        sa.column("owner"),
        sa.column("method"),
        sa.column("source"),
        sa.column("parts"),
        sa.column("expected_min"),
        sa.column("expected_max"),
        sa.column("level_symbol"),
        schema=S,
    )
    op.bulk_insert(
        index_def,
        [
            {
                "code": "SP500",
                "name": "S&P 500",
                "owner": "S&P Dow Jones Indices",
                "method": "fund_file",
                "source": "ishares:IVV",
                "parts": None,
                "expected_min": 495,
                "expected_max": 510,
                "level_symbol": "SPX",
            },
            {
                "code": "R1000",
                "name": "Russell 1000",
                "owner": "FTSE Russell",
                "method": "fund_file",
                "source": "ishares:IWB",
                "parts": None,
                "expected_min": 950,
                "expected_max": 1060,
                "level_symbol": None,
            },
            {
                "code": "R2000",
                "name": "Russell 2000",
                "owner": "FTSE Russell",
                "method": "fund_file",
                "source": "ishares:IWM",
                "parts": None,
                "expected_min": 1850,
                "expected_max": 2100,
                "level_symbol": None,
            },
            {
                "code": "R3000",
                "name": "Russell 3000",
                "owner": "FTSE Russell",
                "method": "union",
                "source": None,
                "parts": "R1000,R2000",
                "expected_min": 2800,
                "expected_max": 3160,
                "level_symbol": None,
            },
        ],
    )


def downgrade() -> None:
    for table in (
        "job_run",
        "index_member_hist",
        "security_symbol_hist",
        "index_member",
        "source_file",
        "index_def",
        "security_symbol",
        "security",
        "company",
    ):
        op.drop_table(table, schema=S)
