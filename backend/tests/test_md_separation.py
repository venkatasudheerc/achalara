"""Market data stays able to run on another machine: these hold that line."""
import ast
from datetime import date
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.md import read as md_read
from app.md.models import JobRun, Security, SecurityClassification, SecuritySymbol
from app.md.seed import seed_securities
from app.services.held_symbols import held_symbols
from app.models import Account, Client, Sleeve, Strategy
from app.models.trade import Trade
from app.services.webull_market_data import WebullMarketDataService
from app.utils.symbols import app_symbol, figi_symbol, webull_symbol
from app.utils.webull_signing import signature

BACKEND = Path(__file__).resolve().parent.parent
APP = BACKEND / "app"

# Outside the package, only these may be imported; the CLI is an operator's tool.
ALLOWED_FROM_OUTSIDE = {"app.md.read", "app.md.schedule"}
OUTSIDE_EXCEPTIONS = {
    "cli.py": ("app.md",),
    "models/__init__.py": ("app.md.models",),
}
# Inside the package, only these parts of the app may be imported.
ALLOWED_FROM_INSIDE = ("app.md", "app.config", "app.models.base", "app.utils")
# The worker is where the two meet: it hands md the symbols the app holds.
WORKER_ALSO = ("app.db.database", "app.services.held_symbols")


def _imports(path: Path):
    """Every ``app...`` module this file imports, at any depth."""
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "app":
                    yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == "app":
                for alias in node.names:
                    yield f"{node.module}.{alias.name}"


def _under(module: str, prefixes) -> bool:
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def test_the_app_reaches_market_data_only_through_its_read_module():
    wrong = []
    for path in APP.rglob("*.py"):
        relative = path.relative_to(APP).as_posix()
        if relative.startswith("md/"):
            continue
        for module in _imports(path):
            if not _under(module, ("app.md",)):
                continue
            allowed = OUTSIDE_EXCEPTIONS.get(relative, ())
            if not _under(module, ALLOWED_FROM_OUTSIDE) and not _under(module, allowed):
                wrong.append(f"{relative}: {module}")
    assert wrong == []


def test_market_data_does_not_reach_into_the_app():
    wrong = []
    for path in (APP / "md").rglob("*.py"):
        allowed = ALLOWED_FROM_INSIDE
        if path.name == "worker.py":
            allowed += WORKER_ALSO
        for module in _imports(path):
            if not _under(module, allowed):
                wrong.append(f"{path.name}: {module}")
    assert wrong == []


def test_market_data_has_no_foreign_key_out_of_its_schema():
    source = (APP / "md" / "models.py").read_text()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ForeignKey":
            target = node.args[0]
            assert isinstance(target, ast.JoinedStr), ast.dump(target)
            assert ast.dump(target.values[0]).count("SCHEMA") == 1


def _script(section: str) -> ScriptDirectory:
    config = Config(str(BACKEND / "alembic.ini"), ini_section=section)
    config.set_main_option(
        "script_location", str(BACKEND / config.get_main_option("script_location"))
    )
    return ScriptDirectory.from_config(config)


def test_the_two_migration_histories_are_apart():
    app, md = _script("alembic"), _script("md")
    assert len(app.get_heads()) == 1
    assert len(md.get_heads()) == 1
    app_ids = {rev.revision for rev in app.walk_revisions()}
    md_revisions = list(md.walk_revisions())
    assert not app_ids & {rev.revision for rev in md_revisions}
    # md's history starts from nothing rather than from one of the app's.
    assert sum(1 for rev in md_revisions if rev.down_revision is None) == 1
    for rev in app.walk_revisions():
        assert 'schema="md"' not in Path(rev.path).read_text()
        assert "CREATE SCHEMA IF NOT EXISTS md" not in Path(rev.path).read_text()


@pytest.mark.parametrize(
    "raw, app, webull, figi",
    [
        ("XYZ B", "XYZ.B", "XYZ B", "XYZ/B"),
        ("XYZ.B", "XYZ.B", "XYZ B", "XYZ/B"),
        ("XYZ-B", "XYZ.B", "XYZ B", "XYZ/B"),
        ("XYZ/B", "XYZ.B", "XYZ B", "XYZ/B"),
        ("nyse:xyz.b", "XYZ.B", "XYZ B", "XYZ/B"),
        (" abc ", "ABC", "ABC", "ABC"),
        (None, "", "", ""),
    ],
)
def test_one_conversion_between_spellings(raw, app, webull, figi):
    assert app_symbol(raw) == app
    assert webull_symbol(raw) == webull
    assert figi_symbol(raw) == figi


def test_signing_is_unchanged_by_the_move():
    """Values produced by the code before it moved; a change here breaks every call."""
    args = ("test-key", "test-secret", "api.webull.com")
    stamp = ("2026-01-02T03:04:05Z", "abc123")
    assert (
        signature(
            *args,
            "/market-data/stocks/bars/list",
            {"symbol": "AAA B", "count": "5"},
            None,
            *stamp,
        )
        == "dEL9SAJw6rnV7500c6cGwxptpNI="
    )
    assert (
        signature(*args, "/market-data/x", {}, '{"a":1}', *stamp)
        == "rjfMTWXFfNMdjq7Fhb/7i35iA+8="
    )


def test_a_quote_comes_back_under_the_spelling_it_was_asked_by(monkeypatch):
    service = WebullMarketDataService()
    monkeypatch.setattr(service, "app_key", "key")
    monkeypatch.setattr(service, "app_secret", "secret")
    monkeypatch.setattr(service, "_rate_limit", lambda: None)
    asked = []

    def snapshots(batch):
        asked.extend(batch)
        return [{"symbol": "XYZ B", "price": "10.5", "pre_close": "10"}]

    monkeypatch.setattr(service, "_get_snapshots", snapshots)
    quotes = service.get_quotes(["XYZ.B"])
    assert asked == ["XYZ B"]
    assert quotes["XYZ.B"][0] == quotes["XYZ B"][0]


def test_seeding_takes_a_list_and_spells_it_in_md(db):
    added = seed_securities(
        db,
        [
            ("NYSE:XYZ B", "STOCK"),
            ("XYZ.B", "ETF"),
            ("ABC", None),
            ("~A NAME", "STOCK"),
        ],
        date(2026, 10, 18),
    )
    assert added == 2
    kinds = {
        symbol: kind
        for symbol, kind in db.query(SecuritySymbol.symbol, Security.kind).join(
            Security
        )
    }
    assert kinds == {"XYZ.B": "stock", "ABC": "other"}


def test_held_symbols_leave_out_options(db):
    client = Client(name="Test Client", email="md-separation@example.com")
    strategy = Strategy(name="Separation test")
    db.add_all([client, strategy])
    db.flush()
    account = Account(client_id=client.id, name="Test account")
    db.add(account)
    db.flush()
    sleeve = Sleeve(account_id=account.id, strategy_id=strategy.id)
    db.add(sleeve)
    db.flush()
    for symbol in ("XYZ B", "XYZ271217P00100000"):
        db.add(
            Trade(
                sleeve_id=sleeve.id,
                symbol=symbol,
                action="BUY",
                quantity=1,
                price=1,
                trade_date=date(2026, 1, 2),
                security_type="STOCK",
            )
        )
    db.flush()
    assert held_symbols(db) == [("XYZ B", "STOCK")]


def _stock(db, symbol, kind="stock"):
    security = Security(name=symbol, kind=kind)
    db.add(security)
    db.flush()
    db.add(SecuritySymbol(security_id=security.id, symbol=symbol))
    return security


def test_a_sector_is_found_whichever_way_the_app_spells_the_symbol(db):
    _stock(db, "XYZ.B")
    classified = _stock(db, "ABC")
    db.add(SecurityClassification(security_id=classified.id, as_of=date(2026, 10, 18)))
    db.flush()
    assert md_read.stocks_without_sector(db, ["XYZ B", "XYZ.B"]) == 1
    assert md_read.stocks_without_sector(db, ["NOPE"]) == 0
    assert md_read.stocks_without_sector(db, []) == 0


def test_system_status_says_when_market_data_cannot_be_read(client, monkeypatch):
    def gone(*args):
        raise md_read.MdUnavailable("OperationalError")

    monkeypatch.setattr(md_read, "last_run", gone)
    monkeypatch.setattr(md_read, "has_run", gone)
    response = client.get("/api/v1/admin/status")
    assert response.status_code == 200
    body = response.json()
    assert "Market data's database could not be read." in body["attention"]
    assert {j["id"] for j in body["jobs"]} >= {"md_index_membership"}


def test_a_separate_market_data_database_that_is_down_is_reported(db, monkeypatch):
    from sqlalchemy.exc import OperationalError

    class Broken:
        def query(self, *args):
            raise OperationalError("select", {}, Exception("down"))

        def close(self):
            pass

    monkeypatch.setattr(md_read, "separate", lambda: True)
    monkeypatch.setattr(md_read, "MdSession", Broken)
    with pytest.raises(md_read.MdUnavailable):
        md_read.last_run(db, "md_classification")


def test_last_run_ignores_a_run_still_going(db):
    assert md_read.last_run(db, "some_job") is None
    assert md_read.has_run(db, "some_job") is False
    from datetime import datetime, timezone

    db.add(
        JobRun(
            job="some_job",
            started_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
            outcome="running",
        )
    )
    db.flush()
    assert md_read.last_run(db, "some_job") is None
    assert md_read.has_run(db, "some_job") is True
