"""Where your data comes from: the viewer's own Plaid logins, and, read-only,
the logins of others that feed an account in view; nothing else, and never a key."""
from datetime import datetime, timedelta, timezone

from app.models.brokerage_connection import BrokerageAccount, BrokerageConnection
from tests.test_roles import _browser, people  # noqa: F401  (fixture)

CONNECTIONS = "/api/v1/portal/connections"


def _login(db, owner, institution, feeds, status="active", consent=None):
    login = BrokerageConnection(
        client_id=owner.id, source="plaid", external_user_id=owner.id,
        external_connection_id=f"item-{institution}-{owner.name}", institution=institution,
        status=status, access_token_enc="sealed-key-never-returned", consent_expires_at=consent,
    )
    db.add(login)
    db.flush()
    for n, account in enumerate(feeds):
        db.add(BrokerageAccount(
            connection_id=login.id, external_account_ref=f"acct-{n}", name=account.name,
            account_id=account.id, status="mapped",
            last_synced_at=datetime(2026, 11, 13, 11, 30, tzinfo=timezone.utc),
        ))
    db.commit()
    return login


def test_own_logins_and_a_spouses_read_only_and_nothing_else(db, people):  # noqa: F811
    pat_login = _login(db, people["pat"], "Bank AAA", [people["Pat brokerage"], people["Pat private"]])
    # Sam's login feeds Sam's IRA (Pat sees it) and Sam's private account (Pat does not).
    _login(db, people["sam"], "Broker BBB", [people["Sam IRA"], people["Sam private"]], status="broken")
    _login(db, people["lee"], "Broker CCC", [people["Lee brokerage"]])  # outside the family
    # A login of Pat's that feeds nothing yet is still Pat's to see.
    _login(db, people["pat"], "Card DDD", [],
           consent=datetime.now(timezone.utc) + timedelta(days=10))

    response = _browser("login-pat@example.com").get(CONNECTIONS)
    assert response.status_code == 200
    body = response.json()
    assert "sealed-key" not in response.text and "access_token" not in response.text
    by_institution = {c["institution"]: c for c in body["connections"]}
    assert set(by_institution) == {"Bank AAA", "Card DDD", "Broker BBB"}

    mine = by_institution["Bank AAA"]
    assert mine["id"] == pat_login.id and mine["own"] is True and mine["state"] == "sharing"
    assert sorted(a["name"] for a in mine["accounts"]) == ["Pat brokerage", "Pat private"]
    assert mine["last_refreshed_at"].startswith("2026-11-13")
    assert mine["accounts"][0]["health"] is not None

    assert by_institution["Card DDD"]["state"] == "consent_ending"
    assert by_institution["Card DDD"]["accounts"] == []

    spouse = by_institution["Broker BBB"]
    assert spouse["own"] is False and spouse["owner_name"] == "Sam Example"
    assert spouse["state"] == "needs_sign_in"
    assert [a["name"] for a in spouse["accounts"]] == ["Sam IRA"]
    # Only the viewer's own logins count as waiting on them.
    assert body["needs_sign_in"] == 0
    # The viewer's own come first.
    assert [c["own"] for c in body["connections"]] == [True, True, False]


def test_a_minor_sees_only_their_own_and_a_preview_sees_what_the_client_does(db, people):  # noqa: F811
    _login(db, people["pat"], "Bank AAA", [people["Pat brokerage"]])
    kit_login = _login(db, people["kit"], "Bank EEE", [people["Kit UTMA"]], status="broken")

    kit = _browser("login-kit@example.com").get(CONNECTIONS).json()
    assert [c["institution"] for c in kit["connections"]] == ["Bank EEE"]
    assert kit["needs_sign_in"] == 1

    pat_sees = _browser("login-pat@example.com").get(CONNECTIONS).json()
    ben_sees = _browser("ben@example.com").get(CONNECTIONS, params={"as_client": people["pat"].id}).json()
    assert ben_sees == pat_sees
    # Kit's login reaches Pat read-only, as a guardian sees the minor's accounts.
    kits = next(c for c in pat_sees["connections"] if c["id"] == kit_login.id)
    assert kits["own"] is False and [a["name"] for a in kits["accounts"]] == ["Kit UTMA"]

    # An advisor cannot look at someone else's client.
    assert _browser("ben@example.com").get(
        CONNECTIONS, params={"as_client": people["lee"].id}).status_code == 404
