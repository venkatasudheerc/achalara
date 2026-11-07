"""add md market: a ticker is unique within a market, and a security has a currency

Revision ID: d1f7a3c8e2b4
Revises: b8e3f41c6a92
Create Date: 2026-11-05 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1f7a3c8e2b4"
down_revision = "b8e3f41c6a92"
branch_labels = None
depends_on = None

S = "md"


def upgrade() -> None:
    market = op.create_table(
        "market",
        sa.Column("code", sa.String(12), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("timezone", sa.String(40), nullable=False),
        sa.Column("mic", sa.String(4)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema=S,
    )
    op.bulk_insert(
        market,
        [
            {
                "code": "US",
                "name": "United States",
                "country": "US",
                "currency": "USD",
                "timezone": "America/New_York",
                "mic": None,
            }
        ],
    )

    # Everything on file today is American; the defaults mark it so, then go.
    us = sa.ForeignKey("md.market.code")
    for table, columns in (
        (
            "security",
            [
                sa.Column(
                    "market_code",
                    sa.String(12),
                    us,
                    nullable=False,
                    server_default="US",
                ),
                sa.Column(
                    "currency", sa.String(3), nullable=False, server_default="USD"
                ),
                sa.Column("isin", sa.String(12)),
                sa.Column("share_class_figi", sa.String(12)),
            ],
        ),
        (
            "security_symbol",
            [
                sa.Column(
                    "market_code",
                    sa.String(12),
                    sa.ForeignKey("md.market.code"),
                    nullable=False,
                    server_default="US",
                ),
            ],
        ),
        (
            "security_symbol_hist",
            [
                sa.Column(
                    "market_code",
                    sa.String(12),
                    sa.ForeignKey("md.market.code"),
                    nullable=False,
                    server_default="US",
                ),
            ],
        ),
    ):
        for column in columns:
            op.add_column(table, column, schema=S)
    for table, column in (
        ("security", "market_code"),
        ("security", "currency"),
        ("security_symbol", "market_code"),
        ("security_symbol_hist", "market_code"),
    ):
        op.alter_column(table, column, server_default=None, schema=S)

    op.create_index("ix_md_security_market_code", "security", ["market_code"], schema=S)
    op.create_index("ix_md_security_isin", "security", ["isin"], schema=S)
    op.create_index(
        "ix_md_security_share_class_figi", "security", ["share_class_figi"], schema=S
    )
    op.drop_constraint(
        "security_symbol_symbol_key", "security_symbol", type_="unique", schema=S
    )
    op.create_unique_constraint(
        "uq_md_security_symbol_market_symbol",
        "security_symbol",
        ["market_code", "symbol"],
        schema=S,
    )


def downgrade() -> None:
    other = (
        op.get_bind()
        .execute(sa.text("select count(*) from md.security where market_code <> 'US'"))
        .scalar()
    )
    if other:
        raise RuntimeError(
            f"{other} securities are outside the US; going back would lose them. "
            "Remove them first if that is what is wanted."
        )
    op.drop_constraint(
        "uq_md_security_symbol_market_symbol",
        "security_symbol",
        type_="unique",
        schema=S,
    )
    op.create_unique_constraint(
        "security_symbol_symbol_key", "security_symbol", ["symbol"], schema=S
    )
    op.drop_index("ix_md_security_share_class_figi", "security", schema=S)
    op.drop_index("ix_md_security_isin", "security", schema=S)
    op.drop_index("ix_md_security_market_code", "security", schema=S)
    op.drop_column("security_symbol_hist", "market_code", schema=S)
    op.drop_column("security_symbol", "market_code", schema=S)
    for column in ("share_class_figi", "isin", "currency", "market_code"):
        op.drop_column("security", column, schema=S)
    op.drop_table("market", schema=S)
