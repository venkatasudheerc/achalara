"""add md return views: day_return, week_return, month_return

Queries over the daily closes, for asking seasonality questions in plain SQL.
``day_return`` is computed when queried; ``week_return`` and ``month_return``
are materialized and refreshed each night after the prices load. Securities use adjusted
closes (basis total), index levels their level (basis price).

Revision ID: b3e8f1a6d2c9
Revises: a7d4e2f9c6b1
Create Date: 2026-11-08 22:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "b3e8f1a6d2c9"
down_revision = "a7d4e2f9c6b1"
branch_labels = None
depends_on = None

CLOSES = """
    select sym.symbol, sec.id as security_id, 'security'::text as kind,
           'total'::text as basis, p.price_date, p.adj_close as close
      from md.price_adj_daily p
      join md.security sec on sec.id = p.security_id
      join md.security_symbol sym on sym.security_id = sec.id
     where sec.market_code = 'US'
    union all
    select l.symbol, null, 'index', 'price', l.price_date, l.close
      from md.index_level_hist l
"""


def upgrade() -> None:
    # Per day: a plain view. Every window is partitioned by symbol and kind, so a
    # query for one symbol reads only that symbol's rows.
    op.execute(
        f"""
        create view md.day_return as
        with closes as ({CLOSES}),
        r as (
            select c.symbol, c.security_id, c.kind, c.basis, c.price_date,
                   c.close / lag(c.close) over w - 1 as ret,
                   row_number() over m as trading_day_of_month,
                   count(*) over m_all - row_number() over m as trading_days_left,
                   min(c.price_date) over s as first_day
              from closes c
            window w as (partition by c.symbol, c.kind order by c.price_date),
                   s as (partition by c.symbol, c.kind),
                   m as (partition by c.symbol, c.kind, date_trunc('month', c.price_date)
                         order by c.price_date),
                   m_all as (partition by c.symbol, c.kind, date_trunc('month', c.price_date))
        )
        select symbol, security_id, kind, basis, price_date,
               extract(year from price_date)::int as year,
               extract(month from price_date)::int as month,
               extract(isodow from price_date)::int as weekday,
               trading_day_of_month::int, trading_days_left::int, ret
          from r
         where ret is not null
           -- The first month on file is left out: its earlier days are missing,
           -- so a day's place in it is not known.
           and date_trunc('month', price_date) > date_trunc('month', first_day)
        """
    )
    # Per week and per month: materialized (about 200,000 rows), refreshed each
    # night after the prices load (md_refresh_returns), so a question across
    # every stock answers in well under a second.
    for name, unit, label_year, label_period, step in (
        ("week_return", "week", "isoyear", "week", "7 days"),
        ("month_return", "month", "year", "month", "1 month"),
    ):
        op.execute(
            f"""
            create materialized view md.{name} as
            with closes as ({CLOSES}),
            ends as (
                select symbol, security_id, kind, basis,
                       date_trunc('{unit}', price_date)::date as period_start,
                       max(price_date) as last_day,
                       (array_agg(close order by price_date desc))[1] as close
                  from closes
                 group by symbol, security_id, kind, basis, date_trunc('{unit}', price_date)
            ),
            r as (
                select *, close / lag(close) over w - 1 as ret,
                       lag(period_start) over w as previous_start
                  from ends
                window w as (partition by symbol, kind order by period_start)
            )
            select symbol, security_id, kind, basis,
                   extract({label_year} from period_start)::int as year,
                   extract({label_period} from period_start)::int as {unit},
                   period_start, last_day, ret
              from r
             where ret is not null
               and previous_start = (period_start - interval '{step}')::date
               -- Only periods that have ended: the last calendar day has passed.
               and (period_start + interval '{step}' - interval '1 day')::date
                   <= current_date
            """
        )
        op.execute(
            f"create unique index ix_md_{name}_key on md.{name} (symbol, kind, period_start)"
        )
        op.execute(f"create index ix_md_{name}_{unit} on md.{name} ({unit}, kind)")


def downgrade() -> None:
    op.execute("drop materialized view if exists md.month_return")
    op.execute("drop materialized view if exists md.week_return")
    op.execute("drop view if exists md.day_return")
