"""Market data's own connection.

``MD_DATABASE_URL`` when ``md`` has a database of its own, otherwise the app's.
Everything in this package opens its sessions here, so moving ``md`` is a
change of setting.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

engine = create_engine(settings.md_database_url or settings.database_url, echo=False)
MdSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def separate() -> bool:
    """Whether ``md`` is in a different database from the app's."""
    return bool(settings.md_database_url) and (
        settings.md_database_url != settings.database_url
    )
