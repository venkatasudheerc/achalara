"""Pytest configuration and fixtures"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient


from app.models.base import Base
from app.md.base import MdBase
import app.md.models  # noqa: F401  (market data keeps its own metadata)


from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.main import app


# Use in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def db_engine():
    """Create test database engine (session-scoped)"""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    # SQLite has no schemas, so the perf and md schemas' tables live in the default one.
    engine = engine.execution_options(schema_translate_map={"perf": None, "md": None})
    Base.metadata.create_all(bind=engine)
    MdBase.metadata.create_all(bind=engine)
    yield engine
    MdBase.metadata.drop_all(bind=engine)
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db(db_engine):
    """Get test database session (function-scoped)"""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(autocommit=False, autoflush=False, bind=connection)()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def no_live_quotes(monkeypatch):
    """Live quotes never reach the network in tests: the source knows nothing
    unless a test hands it prices through ``live_quotes._fetch``."""
    from app.services import live_quotes

    live_quotes.forget()
    monkeypatch.setattr(live_quotes, "_fetch", lambda symbols: {})
    yield
    live_quotes.forget()


@pytest.fixture(autouse=True)
def no_dns(monkeypatch):
    """Email domains are not looked up in tests: every one receives mail unless
    a test says otherwise through ``email_domains.receives_mail``."""
    from app.services import email_domains

    monkeypatch.setattr(email_domains, "receives_mail", lambda email: True)


@pytest.fixture(autouse=True)
def no_real_mail(monkeypatch):
    """No test sends email: the mail service is unconfigured, and a message
    that reaches it anyway fails the test. A test that wants mail configures
    it and replaces ``mailer._post``."""
    from app.config import settings
    from app.services import mailer

    def refuse(api_key, message):
        raise AssertionError("A test tried to send real email")

    monkeypatch.setattr(settings, "resend_api_key", "")
    monkeypatch.setattr(settings, "mail_from", "")
    monkeypatch.setattr(mailer, "_post", refuse)


@pytest.fixture
def client(db):
    """Test client signed in as an advisor, who may call every route.

    The sign-in itself is bypassed here; ``anon_client`` goes through it.
    """

    def override_get_db():
        yield db

    advisor = User(
        id="test-admin", email="admin@example.com", name="Admin", role="admin"
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: advisor
    test_client = TestClient(app)

    yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def anon_client(db):
    """Test client with no session: every call goes through the real sign-in."""

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)

    yield test_client

    app.dependency_overrides.clear()


def create_test_client_and_account(
    test_client,
    client_name="Test Client",
    client_email="test@example.com",
    account_name="Test Account",
):
    """Helper function to create a client and account for testing"""
    client_resp = test_client.post(
        "/api/v1/clients/", json={"name": client_name, "email": client_email}
    )
    client_id = client_resp.json()["id"]

    account_resp = test_client.post(
        f"/api/v1/clients/{client_id}/accounts",
        json={"name": account_name, "description": "Test account"},
    )
    account_id = account_resp.json()["id"]

    return client_id, account_id


def create_test_strategy(
    test_client,
    client_name="Test Client",
    client_email="test@example.com",
    account_name="Test Account",
    strategy_name="Test Strategy",
    strategy_desc="Test",
):
    """Create a client, account, global strategy and sleeve for testing.

    Returns ``(client_id, account_id, sleeve_id)``. The third element is the
    sleeve — the account x strategy instance that owns trades and positions.
    """
    client_id, account_id = create_test_client_and_account(
        test_client, client_name, client_email, account_name
    )

    strategy_resp = test_client.post(
        "/api/v1/strategies/",
        json={"name": strategy_name, "description": strategy_desc},
    )
    strategy_id = strategy_resp.json()["id"]

    sleeve_resp = test_client.post(
        f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves",
        json={"strategy_id": strategy_id},
    )
    sleeve_id = sleeve_resp.json()["id"]

    return client_id, account_id, sleeve_id


class _SharedSession:
    """The test's session, handed to research code as its ReadSession; closing it
    is left to the test."""

    def __init__(self, session):
        self._session = session

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._session, name)


@pytest.fixture(autouse=True)
def research_reads_the_test_db(db, monkeypatch):
    """Research reads md through ReadSession, a read-only connection of its own.
    In tests that is the test's session, so research sees the test's rows; the
    read-only mechanism itself is tested in test_research_guardrails.py."""
    from app.md import read as md_read

    monkeypatch.setattr(md_read, "ReadSession", lambda: _SharedSession(db))
