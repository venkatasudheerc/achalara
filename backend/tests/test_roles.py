"""Admin, advisor and client; spouses, minors and private accounts."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.account import Account
from app.models.client import Client
from app.models.user import User
from app.services.auth_service import AuthService, hash_password

PASSWORD = "a long passphrase 2026"


def _login(db, email, role, client_id=None):
    user = User(email=email, name=email.split("@")[0].title(), role=role, client_id=client_id,
                password_hash=hash_password(PASSWORD))
    db.add(user)
    db.commit()
    return user


def _browser(email):
    browser = TestClient(app)
    assert browser.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return browser


@pytest.fixture
def people(db, anon_client):
    """Ada the admin; Ben, an advisor with Pat and Sam's family; Cy, another
    advisor; Pat and Sam married, Kit their minor; Lee on their own."""
    _login(db, "ada@example.com", "admin")
    ben = _login(db, "ben@example.com", "advisor")
    cy = _login(db, "cy@example.com", "advisor")
    pat = Client(name="Pat Example", email="pat@example.com", advisor_id=ben.id)
    lee = Client(name="Lee Example", email="lee@example.com", advisor_id=cy.id)
    db.add_all([pat, lee])
    db.commit()
    service = AuthService(db)
    sam = service.add_relative(pat.id, "Sam Example", "spouse", "sam@example.com")
    kit = service.add_relative(pat.id, "Kit Example", "minor")
    accounts = {}
    for owner, name, private in (
        (pat, "Pat brokerage", False), (pat, "Pat private", True),
        (sam, "Sam IRA", False), (sam, "Sam private", True),
        (kit, "Kit UTMA", False), (lee, "Lee brokerage", False),
    ):
        accounts[name] = Account(client_id=owner.id, name=name, is_private=private)
    db.add_all(accounts.values())
    db.commit()
    for client in (pat, sam, kit, lee):
        _login(db, f"login-{client.name.split()[0].lower()}@example.com", "client", client.id)
    return {"ben": ben, "cy": cy, "pat": pat, "sam": sam, "kit": kit, "lee": lee, **accounts}


def _sees(db, client):
    return sorted(a.name for a, _ in AuthService(db).accounts_for_client(client.id))


def test_spouses_see_each_other_but_not_what_is_private_and_both_see_their_minor(db, people):
    assert _sees(db, people["pat"]) == ["Kit UTMA", "Pat brokerage", "Pat private", "Sam IRA"]
    assert _sees(db, people["sam"]) == ["Kit UTMA", "Pat brokerage", "Sam IRA", "Sam private"]


def test_a_minor_sees_only_their_own_and_cannot_hide_from_guardians(db, people):
    people["Kit UTMA"].is_private = True
    db.commit()
    assert _sees(db, people["kit"]) == ["Kit UTMA"]
    assert "Kit UTMA" in _sees(db, people["pat"]) and "Kit UTMA" in _sees(db, people["sam"])


def test_someone_outside_the_family_sees_only_their_own(db, people):
    assert _sees(db, people["lee"]) == ["Lee brokerage"]


def test_relationships_have_guardrails(db, people):
    service = AuthService(db)
    with pytest.raises(Exception, match="already has a spouse"):
        service.set_spouse(people["lee"].id, people["pat"].id)
    with pytest.raises(Exception, match="minor cannot have a spouse"):
        service.set_spouse(people["kit"].id, people["lee"].id)
    with pytest.raises(Exception, match="minor cannot add"):
        service.add_relative(people["kit"].id, "Someone", "minor")
    # Ending a marriage ends it on both sides.
    service.set_spouse(people["pat"].id, None)
    db.refresh(people["sam"])
    assert people["sam"].spouse_id is None
    assert "Sam IRA" not in _sees(db, people["pat"])


def test_an_advisor_reaches_only_their_own_clients(db, people):
    ben = _browser("ben@example.com")
    listed = {c["name"] for c in ben.get("/api/v1/clients/").json()}
    assert listed == {"Pat Example", "Sam Example", "Kit Example"}
    assert ben.get(f"/api/v1/clients/{people['pat'].id}").status_code == 200
    assert ben.get(f"/api/v1/clients/{people['lee'].id}").status_code == 403
    assert ben.get(f"/api/v1/portal/accounts?as_client={people['lee'].id}").status_code == 404
    assert ben.get(f"/api/v1/portal/accounts?as_client={people['pat'].id}").status_code == 200
    # The platform's own pages stay with the admin.
    assert ben.get("/api/v1/admin/status").status_code == 403


def test_an_advisors_new_client_is_theirs_and_only_an_admin_assigns_advisors(db, people):
    ben = _browser("ben@example.com")
    made = ben.post("/api/v1/clients/", json={"name": "New Example"}).json()
    assert made["advisor_id"] == people["ben"].id and made["email"] is None
    refused = ben.patch(f"/api/v1/clients/{made['id']}", json={"advisor_id": people["cy"].id})
    assert refused.status_code == 403

    ada = _browser("ada@example.com")
    moved = ada.patch(f"/api/v1/clients/{made['id']}", json={"advisor_id": people["cy"].id})
    assert moved.json()["advisor_id"] == people["cy"].id


def test_only_an_admin_creates_advisors(db, people):
    body = {"name": "Dee Advisor", "email": "dee@example.com"}
    assert _browser("ben@example.com").post("/api/v1/auth/advisors", json=body).status_code == 403
    link = _browser("ada@example.com").post("/api/v1/auth/advisors", json=body)
    assert link.status_code == 201 and link.json()["purpose"] == "invite"
    assert db.query(User).filter(User.email == "dee@example.com").one().role == "advisor"


def test_an_advisor_cannot_invite_or_reset_someone_elses_client(db, people):
    ben = _browser("ben@example.com")
    assert ben.post("/api/v1/auth/invites", json={"client_id": people["lee"].id}).status_code == 404
    lee_login = db.query(User).filter(User.client_id == people["lee"].id).one()
    assert ben.post(f"/api/v1/auth/users/{lee_login.id}/password-reset").status_code == 404


def test_a_client_keeps_their_own_account_private_and_invites_their_family(db, people):
    pat = _browser("login-pat@example.com")
    sam_ira = people["Sam IRA"].id
    assert pat.patch(f"/api/v1/portal/accounts/{sam_ira}", json={"is_private": True}).status_code == 404
    mine = people["Pat brokerage"].id
    assert pat.patch(f"/api/v1/portal/accounts/{mine}", json={"is_private": True}).json() == {"is_private": True}

    relatives = {r["name"]: r for r in pat.get("/api/v1/portal/relatives").json()}
    assert {n: r["relation"] for n, r in relatives.items()} == {"Sam Example": "spouse", "Kit Example": "minor"}
    link = pat.post(f"/api/v1/portal/relatives/{relatives['Kit Example']['id']}/invite",
                    json={"email": "kit@example.com"})
    assert link.status_code == 409  # Kit already has a login in this fixture
    stranger = pat.post(f"/api/v1/portal/relatives/{people['lee'].id}/invite", json={})
    assert stranger.status_code == 404

    kit = _browser("login-kit@example.com")
    assert kit.get("/api/v1/portal/accounts").json()["viewer"]["is_minor"] is True
    assert kit.post("/api/v1/portal/relatives", json={"name": "X", "relation": "minor"}).status_code == 422


def test_an_advisor_sees_and_trades_for_their_own_clients_only(db, people):
    from app.models.sleeve import Sleeve
    from app.models.strategy import Strategy

    strategy = Strategy(name="Core")
    db.add(strategy)
    db.flush()
    mine = Sleeve(account_id=people["Pat brokerage"].id, strategy_id=strategy.id)
    theirs = Sleeve(account_id=people["Lee brokerage"].id, strategy_id=strategy.id)
    db.add_all([mine, theirs])
    db.commit()
    ben = _browser("ben@example.com")

    logins = {u["email"] for u in ben.get("/api/v1/auth/users").json()}
    assert logins == {"login-pat@example.com", "login-sam@example.com", "login-kit@example.com"}

    trade = {"trade_date": "2026-11-02", "symbol": "AAA", "action": "BUY", "quantity": 1, "price": 10}
    assert ben.post("/api/v1/trades/", json={**trade, "sleeve_id": mine.id}).status_code == 201
    assert ben.post("/api/v1/trades/", json={**trade, "sleeve_id": theirs.id}).status_code == 404
