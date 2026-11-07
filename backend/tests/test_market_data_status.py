"""The Market data page's endpoint: read from the database, for advisors only."""
from datetime import date, datetime, timedelta, timezone

from app.md import read as md_read
from app.md.models import (
    IndexDef,
    IndexMember,
    JobRun,
    Security,
    SecurityClassification,
    SourceFile,
)
from app.md.status_report import FILE_STALE_DAYS, PLANNED_TABLES, build_status

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
URL = "/api/v1/admin/market-data/status"


def _index(db, code="XYZ", low=1, high=9):
    db.add(
        IndexDef(
            code=code,
            name="Example",
            owner="Example",
            method="fund_file",
            source="ishares:XYZF",
            expected_min=low,
            expected_max=high,
        )
    )
    db.flush()


def _security(db, kind="stock", **fields):
    security = Security(name="Example", kind=kind, **fields)
    db.add(security)
    db.flush()
    return security


def _file(db, as_of):
    db.add(
        SourceFile(
            source="ishares",
            name="XYZF",
            as_of=as_of,
            content=b"x",
            sha256="0" * 64,
            fetched_at=NOW,
        )
    )
    db.flush()


def _run(db, job="md_identifiers", started=NOW, outcome="ok", **fields):
    db.add(JobRun(job=job, started_at=started, outcome=outcome, **fields))
    db.flush()


def test_an_empty_schema_still_answers(client):
    response = client.get(URL)
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["own_database"] is False
    assert body["coverage"]["securities"] == 0
    assert {j["id"] for j in body["jobs"]} >= {"md_index_membership"}
    assert all(j["outcome"] is None for j in body["jobs"])
    assert "Market data: index membership has not run yet." in body["attention"]
    tables = {t["name"]: t for t in body["tables"]}
    assert tables["job_run"]["kind"] == "operations"
    assert tables["security_symbol_hist"]["kind"] == "history"
    assert tables["security"]["kind"] == "current"


def test_it_shows_what_is_on_file(client, db):
    _index(db)
    stock = _security(db, webull_id="1")
    db.add(IndexMember(index_code="XYZ", security_id=stock.id, since=date(2026, 10, 1)))
    db.flush()
    body = client.get(URL).json()
    index = body["indices"][0]
    assert (index["code"], index["members"], index["in_range"]) == ("XYZ", 1, True)
    assert index["source"] == "ishares:XYZF"
    assert body["coverage"]["by_kind"] == [{"name": "stock", "count": 1}]
    assert body["coverage"]["by_market"] == [{"name": "US", "count": 1}]
    webull = body["coverage"]["measures"][0]
    assert (webull["label"], webull["count"], webull["of"]) == ("Webull id", 1, 1)


def test_sector_coverage_counts_stocks_only(db):
    """A fund has no sector by design, so it must not look like a gap."""
    stock = _security(db)
    _security(db, kind="etf")
    other = _security(db, kind="other")
    for security, code in ((stock, "IT"), (other, "IT")):
        db.add(
            SecurityClassification(
                security_id=security.id,
                sector_code=code,
                sector_source="ishares",
                as_of=date(2026, 10, 1),
            )
        )
    db.flush()
    measures = {
        m["label"]: m for m in build_status(db, False, NOW)["coverage"]["measures"]
    }
    assert (measures["Sector"]["count"], measures["Sector"]["of"]) == (1, 1)
    assert measures["Sector"]["of_label"] == "stocks"
    assert measures["FIGI"]["of"] == 3


def test_attention_names_what_needs_a_look(db):
    _index(db, low=5, high=9)
    _file(db, NOW.date() - timedelta(days=FILE_STALE_DAYS))
    _run(db, "md_identifiers", outcome="failed", note="boom")
    _run(db, "md_seed_holdings", started=NOW - timedelta(days=4))
    _run(db, "md_classification", started=NOW - timedelta(days=9), outcome="running")
    attention = build_status(db, False, NOW)["attention"]
    assert "Market data: identifiers failed on its last run." in attention
    assert "Market data: held securities last ran 4 days ago." in attention
    assert "XYZ has 0 members, outside what is expected." in attention
    assert any(line.startswith("The newest index file is from") for line in attention)
    assert not any("sectors and industries" in line for line in attention)


def test_recent_files_and_runs_need_no_look(db):
    _index(db, low=0, high=9)
    _file(db, NOW.date() - timedelta(days=FILE_STALE_DAYS - 1))
    _run(db, "md_seed_holdings", started=NOW - timedelta(days=3))
    attention = build_status(db, False, NOW)["attention"]
    assert not any("newest index file" in line for line in attention)
    assert not any("held securities" in line for line in attention)


def test_it_lists_only_what_is_not_built(client):
    names = {row["name"] for row in client.get(URL).json()["not_built"]}
    assert {name for name, _ in PLANNED_TABLES} <= names
    assert "security" not in names
    assert "fx_rate_hist" in names


def test_reading_it_changes_nothing(db):
    _security(db)
    build_status(db, False, NOW)
    assert not db.new and not db.dirty and not db.deleted


def test_a_separate_database_that_is_down_is_reported_not_raised(client, monkeypatch):
    def gone(app_db):
        raise md_read.MdUnavailable("OperationalError")

    monkeypatch.setattr(md_read, "_status", gone)
    response = client.get(URL)
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["attention"] == ["Market data's database could not be read."]
    assert body["coverage"] is None


def test_it_is_not_open_to_the_public(anon_client):
    assert anon_client.get(URL).status_code == 401
