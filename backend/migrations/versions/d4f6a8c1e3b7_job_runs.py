"""Scheduled job runs, kept across restarts.

The record of when each daily job last ran lived only in the running process,
so a restart forgot it: System status showed "not run yet", and a run that fell
while the server was down was never made up. Each finished run is now a row
here; the scheduler reads it at start-up (``scheduler.catch_up``).

Revision ID: d4f6a8c1e3b7
Revises: b7d2e9a4c1f3
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op

revision = "d4f6a8c1e3b7"
down_revision = "b7d2e9a4c1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(400)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_job_runs_job_id", "job_runs", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_runs_job_id", table_name="job_runs")
    op.drop_table("job_runs")
