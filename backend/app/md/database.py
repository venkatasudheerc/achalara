"""Market data's own connections.

``MD_DATABASE_URL`` when ``md`` has a database of its own, otherwise the app's.
Everything in this package opens its sessions here, so moving ``md`` is a
change of setting.

``ReadSession`` is for research and the chatbot only: it connects as the
read-only role ``md_reader`` when ``MD_READ_DATABASE_URL`` is set, and every
one of its connections is read-only whatever the login, so nothing it runs can
change data. The worker's jobs use ``MdSession``.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.md.config import settings

engine = create_engine(settings.url, echo=False)
MdSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def separate() -> bool:
    """Whether ``md`` is in a different database from the app's."""
    return settings.separate


def _read_only_engine(url: str):
    if url.startswith("sqlite"):
        engine = create_engine(url, echo=False)

        @event.listens_for(engine, "connect")
        def _query_only(connection, _record):  # pragma: no cover - SQLite only
            connection.execute("PRAGMA query_only = ON")

        return engine
    return create_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )


read_engine = _read_only_engine(settings.read_url)
ReadSession = sessionmaker(autocommit=False, autoflush=False, bind=read_engine)
