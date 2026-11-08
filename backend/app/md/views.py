"""Refreshing the stored return views (``md.week_return``, ``md.month_return``).

They are materialized so a question across every stock answers at once, and
refreshed each night after the prices load. ``CONCURRENTLY`` lets them be read
while they refresh. ``md.day_return`` is a plain view and needs nothing.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.md.jobs import tracked_run

JOB = "md_refresh_returns"
MATERIALIZED = ("md.week_return", "md.month_return")


def refresh_return_views(db: Session) -> str:
    with tracked_run(db, JOB) as run:
        if db.get_bind().dialect.name != "postgresql":
            run.outcome, run.note = "skipped", "Not Postgres; no views to refresh"
            return run.note
        for view in MATERIALIZED:
            db.execute(text(f"refresh materialized view concurrently {view}"))
        db.commit()
        run.note = "Refreshed " + ", ".join(MATERIALIZED)
        return run.note
