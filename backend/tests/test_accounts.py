"""Tests for account endpoints"""

from tests.conftest import create_test_client_and_account


def test_create_account(client):
    client_resp = client.post(
        "/api/v1/clients/", json={"name": "Acc Client", "email": "acc@example.com"}
    )
    client_id = client_resp.json()["id"]

    resp = client.post(
        f"/api/v1/clients/{client_id}/accounts",
        json={
            "name": "Brokerage",
            "description": "Main account",
            "account_number": "ACC-001",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Brokerage"
    assert data["account_number"] == "ACC-001"
    assert data["client_id"] == client_id


def test_create_account_client_not_found(client):
    resp = client.post(
        "/api/v1/clients/nonexistent/accounts",
        json={"name": "X"},
    )
    assert resp.status_code == 404


def test_list_accounts(client):
    client_resp = client.post(
        "/api/v1/clients/", json={"name": "List Client", "email": "list@example.com"}
    )
    client_id = client_resp.json()["id"]

    client.post(f"/api/v1/clients/{client_id}/accounts", json={"name": "Acc A"})
    client.post(f"/api/v1/clients/{client_id}/accounts", json={"name": "Acc B"})

    resp = client.get(f"/api/v1/clients/{client_id}/accounts")
    assert resp.status_code == 200
    names = [a["name"] for a in resp.json()]
    assert "Acc A" in names
    assert "Acc B" in names


def test_list_accounts_client_not_found(client):
    resp = client.get("/api/v1/clients/nonexistent/accounts")
    assert resp.status_code == 404


def test_get_account(client):
    client_id, account_id = create_test_client_and_account(client)

    resp = client.get(f"/api/v1/clients/{client_id}/accounts/{account_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == account_id


def test_get_account_not_found(client):
    client_resp = client.post(
        "/api/v1/clients/", json={"name": "NF Client", "email": "nf@example.com"}
    )
    client_id = client_resp.json()["id"]

    resp = client.get(f"/api/v1/clients/{client_id}/accounts/does-not-exist")
    assert resp.status_code == 404


def test_list_accounts_includes_those_shared_with_the_client(client):
    """An agent on a relative's account sees it listed, marked as shared."""

    def new_client(name):
        body = {"name": name, "email": f"{name.lower()}@example.com"}
        return client.post("/api/v1/clients/", json=body).json()["id"]

    agent, relative = new_client("Agent"), new_client("Relative")
    own = client.post(f"/api/v1/clients/{agent}/accounts", json={"name": "Own"}).json()
    theirs = client.post(
        f"/api/v1/clients/{relative}/accounts", json={"name": "Theirs"}
    ).json()
    client.post(
        f"/api/v1/clients/{agent}/account-access", json={"account_id": theirs["id"]}
    )

    listed = client.get(f"/api/v1/clients/{agent}/accounts").json()

    assert [(a["id"], a["shared"]) for a in listed] == [
        (own["id"], False),
        (theirs["id"], True),
    ]
    # The owner is still the relative, and says so.
    assert (listed[1]["client_id"], listed[1]["owner_name"]) == (relative, "Relative")
    # The owner's own list is unchanged, and owned-only is still available.
    owned = client.get(
        f"/api/v1/clients/{agent}/accounts", params={"include_shared": "false"}
    ).json()
    assert [a["id"] for a in owned] == [own["id"]]
    assert [
        a["shared"] for a in client.get(f"/api/v1/clients/{relative}/accounts").json()
    ] == [False]
