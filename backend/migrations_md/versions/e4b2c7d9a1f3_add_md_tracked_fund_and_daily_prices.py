"""add md tracked funds and daily prices as traded

Revision ID: e4b2c7d9a1f3
Revises: d1f7a3c8e2b4
Create Date: 2026-11-08 12:00:00.000000

"""
import uuid
from datetime import date

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e4b2c7d9a1f3"
down_revision = "d1f7a3c8e2b4"
branch_labels = None
depends_on = None

S = "md"

# The starting list: generic public funds. Personal picks go in by hand
# (md-track-fund), never here.
STARTING_FUNDS = (
    ("benchmark", ("SPY", "QQQ", "DIA", "AGG")),
    (
        "sector",
        ("XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"),
    ),
    ("broad_market", ("IVV", "VTI", "IWB", "IWM")),
    ("international", ("EFA", "EEM")),
    ("long_bond", ("TLT",)),
    ("gold", ("GLD",)),
    ("silver", ("SLV",)),
)


def _times():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "tracked_fund",
        sa.Column(
            "security_id",
            sa.String(36),
            sa.ForeignKey("md.security.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("asset_group", sa.String(30), nullable=False),
        sa.Column("added_on", sa.Date(), nullable=False),
        sa.Column("removed_on", sa.Date()),
        sa.Column("note", sa.String(200)),
        *_times(),
        schema=S,
    )
    op.create_table(
        "price_daily_hist",
        sa.Column(
            "security_id",
            sa.String(36),
            sa.ForeignKey("md.security.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("price_date", sa.Date(), primary_key=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("open", sa.Numeric(18, 6)),
        sa.Column("high", sa.Numeric(18, 6)),
        sa.Column("low", sa.Numeric(18, 6)),
        sa.Column("close", sa.Numeric(18, 6), nullable=False),
        sa.Column("volume", sa.BigInteger()),
        sa.Column("last_trade_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(20), nullable=False),
        *_times(),
        schema=S,
    )
    op.create_index(
        "ix_md_price_daily_hist_price_date",
        "price_daily_hist",
        ["price_date"],
        schema=S,
    )

    bind = op.get_bind()
    today = date.today()
    for group, symbols in STARTING_FUNDS:
        for symbol in symbols:
            security_id = bind.execute(
                sa.text(
                    "select security_id from md.security_symbol "
                    "where market_code = 'US' and symbol = :s"
                ),
                {"s": symbol},
            ).scalar()
            if security_id is None:
                security_id = str(uuid.uuid4())
                bind.execute(
                    sa.text(
                        "insert into md.security (id, name, kind, status, market_code,"
                        " currency, created_at, updated_at) values (:id, :s, 'etf',"
                        " 'active', 'US', 'USD', now(), now())"
                    ),
                    {"id": security_id, "s": symbol},
                )
                bind.execute(
                    sa.text(
                        "insert into md.security_symbol (security_id, symbol,"
                        " market_code, created_at, updated_at)"
                        " values (:id, :s, 'US', now(), now())"
                    ),
                    {"id": security_id, "s": symbol},
                )
                bind.execute(
                    sa.text(
                        "insert into md.security_symbol_hist (security_id, symbol,"
                        " market_code, valid_from, source, created_at, updated_at)"
                        " values (:id, :s, 'US', :d, 'tracked_fund', now(), now())"
                    ),
                    {"id": security_id, "s": symbol, "d": today},
                )
            bind.execute(
                sa.text(
                    "insert into md.tracked_fund (security_id, asset_group, added_on,"
                    " created_at, updated_at) values (:id, :g, :d, now(), now())"
                    " on conflict (security_id) do nothing"
                ),
                {"id": security_id, "g": group, "d": today},
            )


def downgrade() -> None:
    # Funds the upgrade added to the security master stay: securities are kept.
    op.drop_index("ix_md_price_daily_hist_price_date", "price_daily_hist", schema=S)
    op.drop_table("price_daily_hist", schema=S)
    op.drop_table("tracked_fund", schema=S)
