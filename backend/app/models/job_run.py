"""One run of a scheduled job, kept so a restart does not forget it"""
import uuid

from sqlalchemy import Boolean, Column, DateTime, String

from app.models.base import BaseModel


class JobRun(BaseModel):
    """When a daily job ran and whether it logged an error.

    The running process also keeps its latest runs in memory (``run_log``);
    this is the lasting copy. System status reads it after a restart, and the
    scheduler reads it at start-up to see whether a run was missed while the
    server was down. It names a job, never a client or an account.
    """

    __tablename__ = "job_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(40), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=False)
    ok = Column(Boolean, nullable=False)
    error = Column(String(400))
