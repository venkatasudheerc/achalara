"""Requests for an invitation: the public form and the adviser's list."""
import pytest

from app.models.invitation_request import InvitationRequest
from app.services import invitation_service

FORM = "/api/v1/invitation-requests"
LIST = "/api/v1/admin/invitation-requests"
# The answer to every request on a server without email set up.
RECEIVED = {"received": True, "confirm_by_email": False}


@pytest.fixture(autouse=True)
def fresh_limits():
    invitation_service.forget()
    yield
    invitation_service.forget()


NOTE = "A friend showed me her portfolio page. I would like one for my accounts."


def _ask(browser, name="Nila Varma", email="nila@example.com", **extra):
    form = {"name": name, "email": email, "phone": "+1 (555) 010-0142", "note": NOTE}
    return browser.post(FORM, json={**form, **extra})


def test_a_visitor_who_is_not_signed_in_can_leave_a_request(anon_client, db):
    resp = _ask(
        anon_client,
        name="  Nila   Varma ",
        email="Nila@Example.com",
        phone=" 555  010 0142 ",
        note="  Saw it at a friend's house and would like   the same for my accounts.  ",
    )
    assert resp.status_code == 202
    assert resp.json() == RECEIVED

    (row,) = db.query(InvitationRequest).all()
    assert (row.name, row.email, row.phone, row.note, row.status) == (
        "Nila Varma",
        "nila@example.com",
        "555 010 0142",
        "Saw it at a friend's house and would like the same for my accounts.",
        "new",
    )


def test_the_list_cannot_be_read_or_changed_without_signing_in(anon_client, db):
    _ask(anon_client)
    (row,) = db.query(InvitationRequest).all()
    assert anon_client.get(LIST).status_code == 401
    patched = anon_client.patch(f"{LIST}/{row.id}", json={"status": "dismissed"})
    assert patched.status_code == 401
    db.refresh(row)
    assert row.status == "new"


def test_the_adviser_reads_the_list_and_marks_a_request(client):
    _ask(client)
    (row,) = client.get(LIST).json()
    assert (row["name"], row["status"], row["handled_at"]) == (
        "Nila Varma",
        "new",
        None,
    )

    changed = client.patch(f"{LIST}/{row['id']}", json={"status": "contacted"})
    assert changed.json()["status"] == "contacted"
    assert changed.json()["handled_at"] is not None
    assert (
        client.patch(f"{LIST}/nobody", json={"status": "dismissed"}).status_code == 404
    )
    assert (
        client.patch(f"{LIST}/{row['id']}", json={"status": "done"}).status_code == 422
    )


def test_requests_still_waiting_come_first(client):
    _ask(client, "First Person", "first@example.com")
    _ask(client, "Second Person", "second@example.com")
    first = next(r for r in client.get(LIST).json() if r["name"] == "First Person")
    client.patch(f"{LIST}/{first['id']}", json={"status": "dismissed"})

    assert [r["name"] for r in client.get(LIST).json()] == [
        "Second Person",
        "First Person",
    ]


def test_a_filled_hidden_field_marks_a_script_and_nothing_is_kept(anon_client, db):
    resp = _ask(anon_client, website="https://spam.example.com")
    assert resp.json() == RECEIVED
    assert db.query(InvitationRequest).count() == 0


def test_the_same_email_asking_again_adds_nothing_until_it_is_answered(client, db):
    _ask(client)
    assert _ask(client, name="Nila V.").json() == RECEIVED
    assert db.query(InvitationRequest).count() == 1

    (row,) = client.get(LIST).json()
    client.patch(f"{LIST}/{row['id']}", json={"status": "dismissed"})
    _ask(client)
    assert db.query(InvitationRequest).count() == 2


def test_one_sender_is_limited_and_is_told_nothing_about_it(anon_client, db):
    for n in range(invitation_service.PER_SENDER + 2):
        resp = _ask(anon_client, email=f"person{n}@example.com")
        assert (resp.status_code, resp.json()) == (202, RECEIVED)
    assert db.query(InvitationRequest).count() == invitation_service.PER_SENDER


def test_no_more_than_a_day_s_worth_is_kept_from_everyone_together(db, monkeypatch):
    monkeypatch.setattr(invitation_service, "PER_DAY", 2)
    service = invitation_service.InvitationService(db)
    kept = [
        service.submit(
            "Person", f"p{n}@example.com", "555 010 0100", NOTE, sender=f"10.0.0.{n}"
        )
        for n in range(4)
    ]
    assert kept == [True, True, False, False]


def test_what_does_not_fit_the_form_is_refused(anon_client, db):
    assert _ask(anon_client, email="not-an-email").status_code == 422
    assert _ask(anon_client, name="   ").status_code == 422
    assert _ask(anon_client, note="   ").status_code == 422
    for phone in ("", "12345", "call me", "555-010-0142 ext nine"):
        assert _ask(anon_client, phone=phone).status_code == 422
    for missing in ("name", "email", "phone", "note"):
        form = {
            "name": "Nila",
            "email": "n@example.com",
            "phone": "5550100142",
            "note": NOTE,
        }
        del form[missing]
        assert anon_client.post(FORM, json=form).status_code == 422
    assert _ask(anon_client, name="x" * 121).status_code == 422
    assert _ask(anon_client, note="x" * 1001).status_code == 422
    assert db.query(InvitationRequest).count() == 0


def test_a_waiting_request_shows_on_system_status_without_a_name(client):
    _ask(client)
    attention = client.get("/api/v1/admin/status").json()["attention"]
    (line,) = [a for a in attention if "invitation" in a]
    assert line == "1 invitation request waiting for a reply."
    assert "Nila" not in line and "nila@" not in line


def test_the_adviser_is_alerted_when_a_request_arrives_and_no_email_is_sent(
    anon_client, monkeypatch
):
    from app.config import settings
    from app.services import alerts

    sent = []
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "1")
    monkeypatch.setattr(alerts, "_post", lambda token, chat, text: sent.append(text))
    monkeypatch.setattr(alerts, "watch", alerts.StatusWatch())

    _ask(anon_client)

    # The no_real_mail fixture fails the test if anything is emailed.
    assert any("1 invitation request waiting" in text for text in sent)
    assert not any("Nila" in text or "nila@" in text for text in sent)


# ---------------------------------------------------------------------------
# Stricter fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, value",
    [
        ("name", "x"),
        ("name", "123"),
        ("name", "asdf@example"),
        ("name", "https://spam.example.com"),
        ("phone", "555 010 014"),  # nine digits
        ("phone", "0000000000"),
        ("phone", "1234567890"),
        ("phone", "9876543210"),
        ("note", "asdf"),
        ("note", "x" * 60),  # long enough, but not words
        ("note", "Interested. Friend told me about it."),  # words, but under 50
    ],
)
def test_junk_that_merely_looks_like_a_field_is_refused(anon_client, db, field, value):
    assert _ask(anon_client, **{field: value}).status_code == 422
    assert db.query(InvitationRequest).count() == 0


@pytest.mark.parametrize(
    "field, value",
    [
        ("name", "Nila D'Souza-Varma"),
        ("name", "J. Ng"),
        ("name", "Zoë Ångström"),
        ("phone", "+91 98450 12345"),
        ("phone", "(555) 010-0142"),
    ],
)
def test_real_names_and_numbers_from_anywhere_are_accepted(anon_client, field, value):
    assert _ask(anon_client, **{field: value}).status_code == 202


def test_an_email_whose_domain_cannot_receive_mail_is_refused(anon_client, monkeypatch):
    from app.services import email_domains

    monkeypatch.setattr(
        email_domains, "receives_mail", lambda email: "nowhere" not in email
    )
    resp = _ask(anon_client, email="nila@nowhere-at-all.com")
    assert resp.status_code == 422
    assert "cannot receive mail" in resp.text


# ---------------------------------------------------------------------------
# Confirming by email
# ---------------------------------------------------------------------------


@pytest.fixture
def outbox(monkeypatch):
    """A configured mail service that keeps what it is handed."""
    from app.config import settings
    from app.services import mailer

    sent = []
    monkeypatch.setattr(settings, "resend_api_key", "test-mail-key")
    monkeypatch.setattr(settings, "mail_from", "Achalara <no-reply@mail.example.com>")
    monkeypatch.setattr(mailer, "_post", lambda key, message: sent.append(message))
    return sent


def _token(message):
    import re

    return re.search(r"/request-invitation/confirm/([\w-]+)", message["text"]).group(1)


def test_with_email_set_up_a_request_counts_only_once_confirmed(client, db, outbox):
    resp = _ask(client)
    assert resp.json() == {"received": True, "confirm_by_email": True}

    # Kept, but not shown, counted or alerted until the visitor confirms.
    assert db.query(InvitationRequest).count() == 1
    assert client.get(LIST).json() == []
    attention = client.get("/api/v1/admin/status").json()["attention"]
    assert not any("invitation" in a for a in attention)

    (message,) = outbox
    assert message["to"] == ["nila@example.com"]
    assert message["subject"] == "Confirm your request to Achalara"
    # Nothing in it but the request having been made; no phone, no note.
    assert "555" not in message["text"] and "portfolio page" not in message["text"]
    token = _token(message)
    # Only a digest of the link is kept.
    assert db.query(InvitationRequest).filter_by(confirm_token_hash=token).count() == 0

    assert client.post(f"{FORM}/confirm", json={"token": token}).json() == {
        "confirmed": True
    }
    (row,) = client.get(LIST).json()
    assert row["name"] == "Nila Varma"
    attention = client.get("/api/v1/admin/status").json()["attention"]
    assert "1 invitation request waiting for a reply." in attention

    # The link works once.
    assert client.post(f"{FORM}/confirm", json={"token": token}).status_code == 404


def test_an_unknown_or_expired_link_confirms_nothing(client, db, outbox):
    from datetime import datetime, timedelta, timezone

    _ask(client)
    token = _token(outbox[0])
    assert (
        client.post(f"{FORM}/confirm", json={"token": "not-a-link"}).status_code == 404
    )

    row = db.query(InvitationRequest).one()
    row.created_at = datetime.now(timezone.utc) - timedelta(hours=49)
    db.commit()
    assert client.post(f"{FORM}/confirm", json={"token": token}).status_code == 404
    assert client.get(LIST).json() == []


def test_an_unconfirmed_request_blocks_a_repeat_until_its_link_runs_out(
    client, db, outbox
):
    from datetime import datetime, timedelta, timezone

    _ask(client)
    _ask(client)
    assert (db.query(InvitationRequest).count(), len(outbox)) == (1, 1)

    # Once its link has expired, the old request is dropped and a new one is kept.
    old = db.query(InvitationRequest).one()
    old_id = old.id
    old.created_at = datetime.now(timezone.utc) - timedelta(hours=49)
    db.commit()
    _ask(client)
    (fresh,) = db.query(InvitationRequest).all()
    assert fresh.id != old_id and len(outbox) == 2


def test_a_script_caught_by_the_hidden_field_gets_no_email_sent(anon_client, outbox):
    _ask(anon_client, website="https://spam.example.com")
    assert outbox == []
