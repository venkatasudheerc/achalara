"""Sign-in, invites, sessions, and what each role may reach."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.account import Account
from app.models.client import Client
from app.models.user import AuthToken, User, UserSession
from app.services.auth_service import (
    LOCK_MINUTES,
    MAX_FAILED_ATTEMPTS,
    SESSION_COOKIE,
    AuthService,
    password_problems,
)

ADVISOR_EMAIL = "advisor@firm.example"
ADVISOR_PASSWORD = "correct horse 42 battery"
CLIENT_PASSWORD = "a long passphrase 2026"


@pytest.fixture
def advisor(db):
    return AuthService(db).create_advisor(
        ADVISOR_EMAIL, "Ada Advisor", ADVISOR_PASSWORD
    )


@pytest.fixture
def household(db):
    """Two clients: Maya with two accounts, Ravi with one."""
    maya = Client(name="Maya Rao", email="maya@example.com")
    ravi = Client(name="Ravi Rao", email="ravi@example.com")
    db.add_all([maya, ravi])
    db.flush()
    accounts = {
        "brokerage": Account(
            client_id=maya.id, name="Brokerage — 12345678", account_number="12345678"
        ),
        "ira": Account(
            client_id=maya.id, name="Rollover IRA", account_number="99990001"
        ),
        "trust": Account(
            client_id=ravi.id, name="Family Trust", account_number="55551180"
        ),
    }
    db.add_all(accounts.values())
    db.commit()
    return {"maya": maya, "ravi": ravi, **accounts}


def sign_in(test_client, email=ADVISOR_EMAIL, password=ADVISOR_PASSWORD):
    return test_client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


@pytest.fixture
def as_advisor(anon_client, advisor):
    assert sign_in(anon_client).status_code == 200
    return anon_client


@pytest.fixture
def as_maya(as_advisor, household):
    """A second browser, signed in as the client Maya through a real invite."""
    link = as_advisor.post(
        "/api/v1/auth/invites", json={"client_id": household["maya"].id}
    ).json()
    browser = TestClient(app)
    accepted = browser.post(
        f"/api/v1/auth/links/{link['token']}/accept", json={"password": CLIENT_PASSWORD}
    )
    assert accepted.status_code == 200
    return browser


# -- signing in ----------------------------------------------------------


def test_data_routes_need_a_session_but_health_does_not(anon_client):
    assert anon_client.get("/api/v1/clients/").status_code == 401
    assert anon_client.get("/api/v1/strategies/").status_code == 401
    assert anon_client.post("/api/v1/admin/rebuild-performance").status_code == 401
    assert anon_client.get("/api/v1/auth/me").status_code == 401
    assert anon_client.get("/health").status_code == 200


def test_sign_in_sets_an_http_only_cookie_and_me_names_the_user(anon_client, advisor):
    response = sign_in(anon_client)

    assert response.status_code == 200
    assert response.json()["role"] == "advisor"
    assert "httponly" in response.headers["set-cookie"].lower()
    assert anon_client.get("/api/v1/auth/me").json()["email"] == ADVISOR_EMAIL
    assert anon_client.get("/api/v1/clients/").status_code == 200


def test_wrong_password_and_unknown_email_get_the_same_answer(anon_client, advisor):
    wrong = sign_in(anon_client, password="not the password 1")
    unknown = sign_in(anon_client, email="nobody@example.com")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_sign_in_pauses_after_repeated_failures(anon_client, advisor):
    for _ in range(MAX_FAILED_ATTEMPTS):
        assert sign_in(anon_client, password="not the password 1").status_code == 401

    locked = sign_in(anon_client)  # even the right password is refused now

    assert locked.status_code == 429
    assert str(LOCK_MINUTES) in locked.json()["detail"]


def test_sign_out_ends_the_session(as_advisor):
    assert as_advisor.post("/api/v1/auth/logout").status_code == 204
    assert as_advisor.get("/api/v1/auth/me").status_code == 401


def test_a_stolen_database_holds_no_password_or_token(as_advisor, db):
    token = as_advisor.cookies.get(SESSION_COOKIE)
    user = db.query(User).filter(User.email == ADVISOR_EMAIL).one()

    assert ADVISOR_PASSWORD not in user.password_hash
    assert user.password_hash.startswith("scrypt$")
    assert db.query(UserSession).filter(UserSession.token_hash == token).count() == 0
    assert db.query(UserSession).count() == 1


def test_password_rules():
    assert password_problems("short1", "maya@example.com")
    assert password_problems("onlylettersnodigits", "maya@example.com")
    assert password_problems("maya is here 2026", "maya@example.com")
    assert password_problems(CLIENT_PASSWORD, "maya@example.com") == []


def test_changing_your_password_ends_your_other_sessions(as_advisor, advisor):
    other_browser = TestClient(app)
    assert sign_in(other_browser).status_code == 200

    changed = as_advisor.post(
        "/api/v1/auth/password",
        json={
            "current_password": ADVISOR_PASSWORD,
            "new_password": "another phrase 77 ok",
        },
    )

    assert changed.status_code == 200
    assert as_advisor.get("/api/v1/auth/me").status_code == 200
    assert other_browser.get("/api/v1/auth/me").status_code == 401
    assert sign_in(TestClient(app)).status_code == 401


# -- invites and resets --------------------------------------------------


def test_invite_shows_the_accounts_then_sets_a_password_once(as_advisor, household, db):
    link = as_advisor.post(
        "/api/v1/auth/invites", json={"client_id": household["maya"].id}
    )
    assert link.status_code == 201
    token = link.json()["token"]
    assert link.json()["path"] == f"/invite/{token}"
    # Only a digest of the link is kept.
    assert db.query(AuthToken).filter(AuthToken.token_hash == token).count() == 0

    browser = TestClient(app)
    preview = browser.get(f"/api/v1/auth/links/{token}").json()
    assert preview["email"] == "maya@example.com"
    assert {a["name"] for a in preview["accounts"]} == {"Brokerage", "Rollover IRA"}

    weak = browser.post(
        f"/api/v1/auth/links/{token}/accept", json={"password": "short"}
    )
    assert weak.status_code == 422

    accepted = browser.post(
        f"/api/v1/auth/links/{token}/accept", json={"password": CLIENT_PASSWORD}
    )
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "client"
    assert browser.get("/api/v1/auth/me").json()["client_id"] == household["maya"].id

    # The link is spent, and the client cannot be invited a second time.
    assert TestClient(app).get(f"/api/v1/auth/links/{token}").status_code == 404
    again = as_advisor.post(
        "/api/v1/auth/invites", json={"client_id": household["maya"].id}
    )
    assert again.status_code == 409


def test_an_invited_client_cannot_sign_in_before_setting_a_password(
    as_advisor, household
):
    as_advisor.post("/api/v1/auth/invites", json={"client_id": household["maya"].id})

    attempt = sign_in(TestClient(app), email="maya@example.com", password="")

    assert attempt.status_code == 401


def test_a_new_invite_replaces_the_previous_link(as_advisor, household):
    body = {"client_id": household["maya"].id}
    first = as_advisor.post("/api/v1/auth/invites", json=body).json()["token"]
    second = as_advisor.post("/api/v1/auth/invites", json=body).json()["token"]

    assert TestClient(app).get(f"/api/v1/auth/links/{first}").status_code == 404
    assert TestClient(app).get(f"/api/v1/auth/links/{second}").status_code == 200


def test_reset_link_replaces_the_password_and_signs_everyone_out(
    as_advisor, as_maya, db
):
    maya = db.query(User).filter(User.email == "maya@example.com").one()
    link = as_advisor.post(f"/api/v1/auth/users/{maya.id}/password-reset").json()
    assert link["purpose"] == "reset" and link["path"].startswith("/reset/")

    fresh = TestClient(app)
    accepted = fresh.post(
        f"/api/v1/auth/links/{link['token']}/accept",
        json={"password": "brand new phrase 31"},
    )

    assert accepted.status_code == 200
    assert as_maya.get("/api/v1/auth/me").status_code == 401  # old session gone
    old = sign_in(TestClient(app), email="maya@example.com", password=CLIENT_PASSWORD)
    assert old.status_code == 401


# -- the sign-in email is the advisor's to set ----------------------------


def test_a_client_can_be_invited_under_a_different_sign_in_email(
    as_advisor, db, household
):
    """The advisor's own login may already use the client's email."""
    maya = household["maya"]
    maya.email = ADVISOR_EMAIL
    db.commit()
    refused = as_advisor.post("/api/v1/auth/invites", json={"client_id": maya.id})
    assert (
        refused.status_code == 409
        and "different sign-in email" in refused.json()["detail"]
    )

    link = as_advisor.post(
        "/api/v1/auth/invites",
        json={"client_id": maya.id, "email": "Maya.Portal@Example.com"},
    )

    assert link.status_code == 201 and link.json()["email"] == "maya.portal@example.com"
    browser = TestClient(app)
    browser.post(
        f"/api/v1/auth/links/{link.json()['token']}/accept",
        json={"password": CLIENT_PASSWORD},
    )
    assert browser.get("/api/v1/auth/me").json()["role"] == "client"
    signed_in = sign_in(
        TestClient(app), email="maya.portal@example.com", password=CLIENT_PASSWORD
    )
    assert signed_in.status_code == 200
    # The advisor's login under the shared address is untouched.
    assert as_advisor.get("/api/v1/auth/me").json()["role"] == "advisor"


def test_an_unaccepted_invite_can_be_reissued_to_a_corrected_address(
    as_advisor, household
):
    body = {"client_id": household["maya"].id}
    first = as_advisor.post("/api/v1/auth/invites", json=body).json()

    second = as_advisor.post(
        "/api/v1/auth/invites", json={**body, "email": "maya.rao@example.org"}
    ).json()

    assert (first["email"], second["email"]) == (
        "maya@example.com",
        "maya.rao@example.org",
    )
    assert (
        TestClient(app).get(f"/api/v1/auth/links/{first['token']}").status_code == 404
    )
    preview = TestClient(app).get(f"/api/v1/auth/links/{second['token']}").json()
    assert preview["email"] == "maya.rao@example.org"


def test_changing_an_active_logins_email_keeps_the_password_and_ends_sessions(
    as_advisor, as_maya, db
):
    maya = db.query(User).filter(User.email == "maya@example.com").one()

    link = as_advisor.patch(
        f"/api/v1/auth/users/{maya.id}/email", json={"email": "maya.new@example.com"}
    )

    assert link.status_code == 200
    assert (link.json()["purpose"], link.json()["email"]) == (
        "reset",
        "maya.new@example.com",
    )
    assert as_maya.get("/api/v1/auth/me").status_code == 401  # signed out everywhere
    old = sign_in(TestClient(app), email="maya@example.com", password=CLIENT_PASSWORD)
    new = sign_in(
        TestClient(app), email="maya.new@example.com", password=CLIENT_PASSWORD
    )
    assert (old.status_code, new.status_code) == (401, 200)
    # The link works too, for choosing a new password under the new address.
    accepted = TestClient(app).post(
        f"/api/v1/auth/links/{link.json()['token']}/accept",
        json={"password": "brand new phrase 31"},
    )
    assert (
        accepted.status_code == 200
        and accepted.json()["email"] == "maya.new@example.com"
    )


def test_changing_the_email_of_an_unaccepted_login_gives_a_fresh_invite(
    as_advisor, household, db
):
    as_advisor.post("/api/v1/auth/invites", json={"client_id": household["maya"].id})
    maya = db.query(User).filter(User.email == "maya@example.com").one()

    link = as_advisor.patch(
        f"/api/v1/auth/users/{maya.id}/email", json={"email": "maya.new@example.com"}
    ).json()

    assert link["purpose"] == "invite" and link["path"].startswith("/invite/")


def test_a_sign_in_email_already_in_use_is_refused(as_advisor, as_maya, db, advisor):
    maya = db.query(User).filter(User.email == "maya@example.com").one()

    taken = as_advisor.patch(
        f"/api/v1/auth/users/{maya.id}/email", json={"email": ADVISOR_EMAIL.upper()}
    )
    same = as_advisor.patch(
        f"/api/v1/auth/users/{maya.id}/email", json={"email": "maya@example.com"}
    )
    advisors_own = as_advisor.patch(
        f"/api/v1/auth/users/{advisor.id}/email", json={"email": "other@firm.example"}
    )

    assert taken.status_code == 409
    assert same.status_code == 200  # her own address is not "in use" against her
    assert advisors_own.status_code == 422
    assert (
        as_advisor.patch(
            "/api/v1/auth/users/nope/email", json={"email": "x@example.com"}
        ).status_code
        == 404
    )


def test_a_client_cannot_change_anyones_sign_in_email(as_maya, db):
    maya = db.query(User).filter(User.email == "maya@example.com").one()

    response = as_maya.patch(
        f"/api/v1/auth/users/{maya.id}/email", json={"email": "elsewhere@example.com"}
    )

    assert response.status_code == 403


def test_only_an_advisor_can_invite_or_list_users(as_maya, household):
    invite = as_maya.post(
        "/api/v1/auth/invites", json={"client_id": household["ravi"].id}
    )

    assert invite.status_code == 403
    assert as_maya.get("/api/v1/auth/users").status_code == 403


# -- what a client may reach ---------------------------------------------


def test_a_client_reads_their_own_client_and_accounts(as_maya, household):
    maya, account = household["maya"], household["brokerage"]
    base = f"/api/v1/clients/{maya.id}"

    assert as_maya.get(base).status_code == 200
    assert as_maya.get(f"{base}/accounts").status_code == 200
    assert as_maya.get(f"{base}/positions").status_code == 200
    assert as_maya.get(f"{base}/accounts/{account.id}").status_code == 200
    assert as_maya.get(f"{base}/accounts/{account.id}/sleeves").status_code == 200
    assert as_maya.get(f"{base}/accounts/{account.id}/positions").status_code == 200


def test_a_client_cannot_reach_anyone_else_or_any_firm_wide_route(as_maya, household):
    maya, ravi, trust = household["maya"], household["ravi"], household["trust"]

    for path in [
        f"/api/v1/clients/{ravi.id}",
        f"/api/v1/clients/{ravi.id}/positions",
        f"/api/v1/clients/{ravi.id}/accounts/{trust.id}",
        f"/api/v1/clients/{ravi.id}/accounts/{trust.id}/sleeves",
        # Someone else's account addressed under the client's own id.
        f"/api/v1/clients/{maya.id}/accounts/{trust.id}/positions",
        "/api/v1/clients/",
        "/api/v1/strategies/",
        "/api/v1/admin/sync-logs",
        f"/api/v1/clients/{maya.id}/connections",
        f"/api/v1/clients/{maya.id}/account-access",
    ]:
        assert as_maya.get(path).status_code == 403, path


def test_a_client_cannot_change_anything(as_maya, household):
    maya, account = household["maya"], household["brokerage"]

    assert (
        as_maya.post(
            f"/api/v1/clients/{maya.id}/accounts", json={"name": "Mine"}
        ).status_code
        == 403
    )
    assert (
        as_maya.post(
            "/api/v1/clients/", json={"name": "New", "email": "new@example.com"}
        ).status_code
        == 403
    )
    assert as_maya.post("/api/v1/admin/rebuild-performance").status_code == 403
    assert (
        as_maya.post(
            f"/api/v1/clients/{maya.id}/accounts/{account.id}/sleeves",
            json={"strategy_id": "anything"},
        ).status_code
        == 403
    )


def test_a_client_may_read_benchmarks(as_maya, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "webull_app_key", "")
    monkeypatch.setattr(settings, "webull_app_secret", "")

    assert as_maya.get("/api/v1/benchmarks/SPY/performance").status_code == 200


def test_me_lists_accounts_without_full_account_numbers(as_maya):
    me = as_maya.get("/api/v1/auth/me").json()

    assert [a["name"] for a in me["accounts"]] == ["Brokerage", "Rollover IRA"]
    assert {a["number_last4"] for a in me["accounts"]} == {"5678", "0001"}
    assert all(not a["shared"] for a in me["accounts"])
    assert "12345678" not in as_maya.get("/api/v1/auth/me").text


# -- sharing an account --------------------------------------------------


def test_a_granted_account_becomes_readable_and_is_marked_shared(
    as_advisor, as_maya, household
):
    maya, ravi, trust = household["maya"], household["ravi"], household["trust"]
    path = f"/api/v1/clients/{ravi.id}/accounts/{trust.id}"
    assert as_maya.get(path).status_code == 403

    granted = as_advisor.post(
        f"/api/v1/clients/{maya.id}/account-access", json={"account_id": trust.id}
    )

    assert granted.status_code == 201
    assert granted.json()["owner_name"] == "Ravi Rao"
    assert as_maya.get(path).status_code == 200
    assert as_maya.get(f"{path}/positions").status_code == 200
    shared = [
        a for a in as_maya.get("/api/v1/auth/me").json()["accounts"] if a["shared"]
    ]
    assert [a["id"] for a in shared] == [trust.id]
    # Sharing one account does not open the rest of its owner's data.
    assert as_maya.get(f"/api/v1/clients/{ravi.id}").status_code == 403
    assert as_maya.get(f"/api/v1/clients/{ravi.id}/positions").status_code == 403
    # ...and still does not let the viewer change anything.
    assert as_maya.post(f"{path}/sleeves", json={"strategy_id": "x"}).status_code == 403


def test_revoking_access_closes_the_account_again(as_advisor, as_maya, household):
    maya, ravi, trust = household["maya"], household["ravi"], household["trust"]
    grants = f"/api/v1/clients/{maya.id}/account-access"
    as_advisor.post(grants, json={"account_id": trust.id})

    assert as_advisor.delete(f"{grants}/{trust.id}").status_code == 204

    assert as_advisor.get(grants).json() == []
    assert (
        as_maya.get(f"/api/v1/clients/{ravi.id}/accounts/{trust.id}").status_code == 403
    )
    assert as_advisor.delete(f"{grants}/{trust.id}").status_code == 404


def test_an_owner_is_not_granted_their_own_account(as_advisor, household):
    maya, account = household["maya"], household["brokerage"]

    response = as_advisor.post(
        f"/api/v1/clients/{maya.id}/account-access", json={"account_id": account.id}
    )

    assert response.status_code == 422


# -- the webhook stays outside sign-in ------------------------------------


def test_webhook_is_judged_by_its_signature_not_by_a_session(anon_client):
    response = anon_client.post("/api/v1/webhooks/snaptrade", json={"eventType": "x"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid signature"
