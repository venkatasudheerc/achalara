"""Market data's own table base, apart from the app's.

Its tables are in their own metadata, so its migrations, its tests and a copy
of the package elsewhere stand on their own. Same common columns as the app's.
"""
from sqlalchemy import Column, DateTime, func
from sqlalchemy.orm import declarative_base

MdBase = declarative_base()


class MdModel(MdBase):
    """Base for every ``md`` table."""

    __abstract__ = True

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now()
    )
