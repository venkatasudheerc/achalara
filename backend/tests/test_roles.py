"""Admin, advisor and client; spouses, minors and private accounts."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.account import Account
from app.models.client import Client
from app.models.user import AccountAccess, User
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
    for owner, name in (
        (pat, "Pat brokerage"), (pat, "Pat private"),
        (sam, "Sam IRA"), (sam, "Sam private"),
        (pat, "Kit UTMA"), (lee, "Lee brokerage"),
    ):
        accounts[name] = Account(client_id=owner.id, name=name)
    accounts["Kit UTMA"].beneficiary_id = kit.id  # held for Kit; Pat is the custodian
    db.add_all(accounts.values())
    db.commit()
    for client in (pat, sam, kit, lee):
        _login(db, f"login-{client.name.split()[0].lower()}@example.com", "client", client.id)
    # Nothing is seen until shared: Pat and Sam share what they want the other to see.
    for who, name in ((sam, "Pat brokerage"), (sam, "Kit UTMA"), (pat, "Sam IRA")):
        db.add(AccountAccess(client_id=who.id, account_id=accounts[name].id))
    # Ben, the advisor, has been shown some of them; not "Pat private".
    for name in ("Pat brokerage", "Kit UTMA", "Sam IRA", "Sam private"):
        db.add(AccountAccess(user_id=ben.id, account_id=accounts[name].id))
    db.commit()
    return {"ben": ben, "cy": cy, "pat": pat, "sam": sam, "kit": kit, "lee": lee, **accounts}


def _sees(db, client):
    return sorted(a.name for a, _ in AuthService(db).accounts_for_client(client.id))


def test_nobody_sees_an_account_until_it_is_shared(db, people):
    assert _sees(db, people["pat"]) == ["Kit UTMA", "Pat brokerage", "Pat private", "Sam IRA"]
    assert _sees(db, people["sam"]) == ["Kit UTMA", "Pat brokerage", "Sam IRA", "Sam private"]
    # Marriage grants nothing by itself: Lee has no spouse and sees only their own.
    assert _sees(db, people["lee"]) == ["Lee brokerage"]


def test_a_minor_sees_the_account_held_for_them_read_only(db, people):
    assert _sees(db, people["kit"]) == ["Kit UTMA"]
    assert dict((a.name, shared) for a, shared in AuthService(db).accounts_for_client(people["kit"].id)) == {"Kit UTMA": True}


def test_relationships_have_guardrails(db, people):
    service = AuthService(db)
    with pytest.raises(Exception, match="already has a spouse"):
        service.set_spouse(people["lee"].id, people["pat"].id)
    with pytest.raises(Exception, match="minor cannot have a spouse"):
        service.set_spouse(people["kit"].id, people["lee"].id)
    with pytest.raises(Exception, match="minor cannot add"):
        service.add_relative(people["kit"].id, "Someone", "minor")
    # Ending a marriage ends it on both sides, and shares stay as they were.
    service.set_spouse(people["pat"].id, None)
    db.refresh(people["sam"])
    assert people["sam"].spouse_id is None
    assert "Sam IRA" in _sees(db, people["pat"])


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


def test_a_client_invites_their_family_and_a_minor_cannot_add_people(db, people):
    pat = _browser("login-pat@example.com")
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


def test_an_owner_names_their_own_account_and_their_spouse_sees_the_name(db, people):
    pat = _browser("login-pat@example.com")
    mine = people["Pat brokerage"].id
    named = pat.patch(f"/api/v1/portal/accounts/{mine}", json={"display_name": "  Pat's   trading account "})
    assert named.json() == {"display_name": "Pat's trading account"}
    sam = _browser("login-sam@example.com")
    listed = {a["id"]: a for a in sam.get("/api/v1/portal/accounts").json()["accounts"]}
    assert listed[mine]["display_name"] == "Pat's trading account"
    assert listed[mine]["name"] == "Pat brokerage"  # the custodian's name stays
    # Too long is refused; a spouse cannot rename it; empty clears it.
    assert pat.patch(f"/api/v1/portal/accounts/{mine}", json={"display_name": "x" * 61}).status_code == 422
    assert sam.patch(f"/api/v1/portal/accounts/{mine}", json={"display_name": "Mine"}).status_code == 404
    assert pat.patch(f"/api/v1/portal/accounts/{mine}", json={"display_name": " "}).json()["display_name"] is None


def test_an_advisor_previewing_names_the_clients_account(db, people):
    ben = _browser("ben@example.com")
    mine = people["Pat brokerage"].id
    named = ben.patch(f"/api/v1/portal/accounts/{mine}?as_client={people['pat'].id}", json={"display_name": "Joint"})
    assert named.json()["display_name"] == "Joint"
    # Not as Lee, who is not Ben's client.
    lee = people["Lee brokerage"].id
    refused = ben.patch(f"/api/v1/portal/accounts/{lee}?as_client={people['lee'].id}", json={"display_name": "X"})
    assert refused.status_code == 404


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


def test_an_advisor_sees_only_what_is_shared_with_them_and_a_count_of_the_rest(db, people):
    ben = _browser("ben@example.com")
    body = ben.get("/api/v1/portal/accounts", params={"as_client": people["pat"].id}).json()
    names = {a["name"] for a in body["accounts"]}
    assert "Pat private" not in names and "Pat brokerage" in names
    assert body["viewer"]["not_shared_with_you"] == 1
    # The staff views follow the same rule.
    staff = {a["name"] for a in ben.get(f"/api/v1/clients/{people['pat'].id}/accounts").json()}
    assert "Pat private" not in staff
    assert ben.get(f"/api/v1/clients/{people['pat'].id}/accounts/{people['Pat private'].id}").status_code in (403, 404)
    # The admin sees everything.
    _login(db, "ada2@example.com", "admin")
    ada = _browser("ada2@example.com")
    assert "Pat private" in {a["name"] for a in ada.get(f"/api/v1/clients/{people['pat'].id}/accounts").json()}


def test_an_owner_shares_and_stops_sharing_and_only_view_is_possible(db, people):
    pat = _browser("login-pat@example.com")
    acct = people["Pat private"].id
    assert pat.post(f"/api/v1/portal/accounts/{acct}/shares", json={"person_id": people["sam"].id}).status_code == 200
    sam = _browser("login-sam@example.com")
    assert acct in {a["id"] for a in sam.get("/api/v1/portal/accounts").json()["accounts"]}
    # Sam can neither share it on nor change owners: not an owner.
    assert sam.post(f"/api/v1/portal/accounts/{acct}/shares", json={"person_id": people["lee"].id}).status_code == 404
    out = pat.request("DELETE", f"/api/v1/portal/accounts/{acct}/shares", params={"person_id": people["sam"].id})
    assert out.status_code == 200 and out.json()["shared_with"] == []
    assert acct not in {a["id"] for a in sam.get("/api/v1/portal/accounts").json()["accounts"]}
    # Someone Pat has not added cannot be shared with.
    assert pat.post(f"/api/v1/portal/accounts/{acct}/shares", json={"person_id": people["lee"].id}).status_code == 404


def test_pat_shares_with_their_advisor_and_changes_owner_without_acceptance(db, people):
    pat = _browser("login-pat@example.com")
    acct = people["Pat private"].id
    assert pat.post(f"/api/v1/portal/accounts/{acct}/shares", json={"advisor": True}).json()["shared_with"][0]["kind"] == "advisor"
    ben = _browser("ben@example.com")
    assert acct in {a["id"] for a in ben.get("/api/v1/portal/accounts", params={"as_client": people["pat"].id}).json()["accounts"]}
    moved = pat.put(f"/api/v1/portal/accounts/{acct}/owners", json={"owner_ids": [people["sam"].id], "keep_view": True})
    assert moved.status_code == 200
    db.refresh(people["Pat private"])
    assert people["Pat private"].client_id == people["sam"].id
    assert acct in {a.id for a, _ in AuthService(db).accounts_for_client(people["pat"].id)}  # kept view
    # A minor cannot own.
    sam = _browser("login-sam@example.com")
    assert sam.put(f"/api/v1/portal/accounts/{acct}/owners", json={"owner_ids": [people["kit"].id]}).status_code == 422


def test_joint_owners_both_control_and_the_linker_controls_until_an_owner_signs_in(db, people):
    pat = _browser("login-pat@example.com")
    acct = people["Pat brokerage"].id
    pat.put(f"/api/v1/portal/accounts/{acct}/owners", json={"owner_ids": [people["pat"].id, people["sam"].id]})
    sam = _browser("login-sam@example.com")
    assert sam.post(f"/api/v1/portal/accounts/{acct}/shares", json={"person_id": people["kit"].id}).status_code == 200
    # Pat links an account for Robin, who has no sign-in: Pat controls it.
    robin = AuthService(db).add_relative(people["pat"].id, "Robin Example", "friend")
    mine = Account(client_id=robin.id, name="Robin IRA", linked_by_id=people["pat"].id)
    db.add(mine)
    db.commit()
    service = AuthService(db)
    assert service.can_control(people["pat"].id, mine) is True
    _login(db, "login-robin@example.com", "client", robin.id)
    assert service.can_control(people["pat"].id, mine) is False  # Robin has taken over


def test_hand_over_needs_the_minor_to_have_a_sign_in(db, people):
    pat = _browser("login-pat@example.com")
    acct = people["Kit UTMA"].id
    people["kit"].guardian_id = people["pat"].id
    db.query(User).filter(User.client_id == people["kit"].id).update({"password_hash": None})
    db.commit()
    assert pat.post(f"/api/v1/portal/accounts/{acct}/hand-over", json={}).status_code == 409


def test_everyone_added_is_listed_in_a_group_with_what_is_shared(db, people):
    pat = _browser("login-pat@example.com")
    pat.post("/api/v1/portal/relatives", json={"name": "Morgan Example", "relation": "friend"})
    body = pat.get("/api/v1/portal/people").json()
    groups = {p["name"]: p["group"] for p in body["people"]}
    assert groups["Sam Example"] == "family" and groups["Morgan Example"] == "others"
    sam = next(p for p in body["people"] if p["name"] == "Sam Example")
    assert sam["you_share"] == 2 and sam["shares_with_you"] == 1
    assert body["advisor"]["not_shared"] >= 1
