"""add md sectors, industries and classification

Revision ID: b8e3f41c6a92
Revises: a5c1e9d27f40
Create Date: 2026-10-18 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b8e3f41c6a92"
down_revision = "a5c1e9d27f40"
branch_labels = None
depends_on = None

S = "md"

SECTORS = [
    ("COM", "Communication Services", 1),
    ("CD", "Consumer Discretionary", 2),
    ("CS", "Consumer Staples", 3),
    ("EN", "Energy", 4),
    ("FIN", "Financials", 5),
    ("HC", "Health Care", 6),
    ("IND", "Industrials", 7),
    ("IT", "Information Technology", 8),
    ("MAT", "Materials", 9),
    ("RE", "Real Estate", 10),
    ("UT", "Utilities", 11),
]


def _times():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.add_column("company", sa.Column("sic_description", sa.String(120)), schema=S)
    op.add_column(
        "security",
        sa.Column("profile_checked_at", sa.DateTime(timezone=True)),
        schema=S,
    )

    op.create_table(
        "sector",
        sa.Column("code", sa.String(4), primary_key=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        *_times(),
        schema=S,
    )
    op.create_table(
        "industry",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scheme", sa.String(12), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("industry_group", sa.String(120)),
        sa.Column("source_code", sa.String(10)),
        sa.Column("sector_code", sa.String(4), sa.ForeignKey("md.sector.code")),
        sa.Column("sector_basis", sa.String(20)),
        *_times(),
        sa.UniqueConstraint("scheme", "name", name="uq_md_industry_scheme_name"),
        schema=S,
    )
    op.create_table(
        "security_classification",
        sa.Column(
            "security_id",
            sa.String(36),
            sa.ForeignKey("md.security.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("sector_code", sa.String(4), sa.ForeignKey("md.sector.code")),
        sa.Column("industry_id", sa.String(36), sa.ForeignKey("md.industry.id")),
        sa.Column("sector_source", sa.String(12)),
        sa.Column("industry_source", sa.String(12)),
        sa.Column("as_of", sa.Date(), nullable=False),
        *_times(),
        schema=S,
    )
    op.create_table(
        "security_classification_hist",
        sa.Column(
            "security_id",
            sa.String(36),
            sa.ForeignKey("md.security.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("source", sa.String(12), primary_key=True),
        sa.Column("valid_from", sa.Date(), primary_key=True),
        sa.Column("valid_to", sa.Date()),
        sa.Column("sector_code", sa.String(4), sa.ForeignKey("md.sector.code")),
        sa.Column("industry_id", sa.String(36), sa.ForeignKey("md.industry.id")),
        sa.Column("raw_sector", sa.String(120)),
        sa.Column("raw_industry", sa.String(240)),
        sa.Column("raw_code", sa.String(10)),
        *_times(),
        schema=S,
    )
    sector = sa.table(
        "sector", sa.column("code"), sa.column("name"), sa.column("sort"), schema=S
    )
    op.bulk_insert(sector, [{"code": c, "name": n, "sort": o} for c, n, o in SECTORS])


def downgrade() -> None:
    for table in (
        "security_classification_hist",
        "security_classification",
        "industry",
        "sector",
    ):
        op.drop_table(table, schema=S)
    op.drop_column("security", "profile_checked_at", schema=S)
    op.drop_column("company", "sic_description", schema=S)
