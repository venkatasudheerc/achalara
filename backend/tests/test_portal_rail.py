"""What the landing page's account list and dashboard read from the portal: each
account's kind and owner and last recorded value, a set of accounts at once, money
in and out separately, and the client's own groups of accounts."""
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.models.brokerage_connection import BrokerageAccount, BrokerageConnection
from app.models.perf import DailyValuation
from app.models.user import AccountAccess
from app.services.account_group_service import AccountGroupService
from app.services.account_kind import CASH, KIDS, RETIREMENT, TAXABLE, account_kind
from tests.test_portal import _browser_for, maya, world  # noqa: F401  (fixtures)

ACCOUNTS = "/api/v1/portal/accounts"
GROUPS = "/api/v1/portal/groups"


@pytest.mark.parametrize(
    "name, kind",
    [
        ("Pat Doe — Brokerage Account — 11112222", TAXABLE),
        ("Pat Doe — Roth IRA Brokerage Account — 11112222", RETIREMENT),
        ("Rollover IRA", RETIREMENT),
        ("Workplace 401(k)", RETIREMENT),
        ("Pat Doe, Lee Doe Cust — UTMA Brokerage Account — 1", KIDS),
        ("College 529 Plan", KIDS),
        ("Pat Doe — Cash Plus Account — 1", CASH),
        ("Pat Doe — 11112222", TAXABLE),
        ("", TAXABLE),
    ],
)
def test_an_accounts_kind_is_read_from_its_name(name, kind):
    assert account_kind(name) == kind


def _valuation(db, account, day, total, cash, flow_in=0, flow_out=0):
    db.add(
        DailyValuation(
            account_id=account.id,
            as_of_date=day,
            securities_value=D(str(total - cash)),
            cash_value=D(str(cash)),
            total_value=D(str(total)),
            flow_in=D(str(flow_in)),
            flow_out=D(str(flow_out)),
            return_factor=D("1"),
            basis="observed",
        )
    )


def test_accounts_carry_owner_kind_last_value_and_source(maya, db, world):  # noqa: F811
    _valuation(db, world["brokerage"], date(2026, 11, 2), 5000, 300)
    _valuation(db, world["brokerage"], date(2026, 11, 3), 5100, 250)
    connection = BrokerageConnection(
        client_id=world["maya"].id,
        source="snaptrade",
        external_user_id="u",
        external_connection_id="c",
        institution="Example Brokerage",
    )
    db.add(connection)
    db.flush()
    db.add(
        BrokerageAccount(
            connection_id=connection.id,
            external_account_ref="r",
            name="Brokerage",
            account_id=world["brokerage"].id,
            status="mapped",
        )
    )
    db.commit()

    accounts = {a["name"]: a for a in maya.get(ACCOUNTS).json()["accounts"]}

    brokerage, ira = accounts["Brokerage"], accounts["Rollover IRA"]
    assert brokerage["owner_name"] == "Maya Rao" and brokerage["kind"] == TAXABLE
    assert (brokerage["value"], brokerage["cash"]) == (5100, 250)
    assert brokerage["as_of"] == "2026-11-03"
    assert brokerage["source"] == "Example Brokerage"
    # No record yet, no link: the fields are empty rather than invented.
    assert ira["kind"] == RETIREMENT
    assert ira["value"] is None and ira["source"] is None


def test_a_shared_account_names_its_owner(maya, db, world):  # noqa: F811
    db.add(AccountAccess(client_id=world["maya"].id, account_id=world["trust"].id))
    db.commit()

    trust = next(a for a in maya.get(ACCOUNTS).json()["accounts"] if a["shared"])

    assert trust["owner_name"] == "Ravi Rao"


def test_a_set_of_accounts_narrows_every_view(maya, world):  # noqa: F811
    brokerage, ira = world["brokerage"].id, world["ira"].id

    both = maya.get(
        "/api/v1/portal/positions", params={"account_ids": [brokerage, ira]}
    )
    ira_only = maya.get("/api/v1/portal/positions", params={"account_ids": [ira]})

    assert {p["symbol"] for p in both.json()["positions"]} >= {"AAPL", "VOO", "VTI"}
    assert {p["symbol"] for p in ira_only.json()["positions"]} == {"VTI"}


def test_a_set_with_an_account_out_of_view_is_refused(maya, world):  # noqa: F811
    response = maya.get(
        "/api/v1/portal/positions",
        params={"account_ids": [world["ira"].id, world["trust"].id]},
    )

    assert response.status_code == 404


def test_money_in_and_out_are_given_apart_and_add_up_to_the_net(
    maya, db, world  # noqa: F811
):
    start = date(2026, 9, 1)
    for i in range(30):
        day = start + timedelta(days=i)
        flow_in = 1000 if i == 5 else 0
        flow_out = 400 if i == 20 else 0
        _valuation(db, world["brokerage"], day, 10000 + i * 10, 500, flow_in, flow_out)
    db.commit()

    body = maya.get(
        "/api/v1/portal/performance",
        params={"account_ids": [world["brokerage"].id], "grain": "month"},
    ).json()

    summary = body["summary"]
    assert (summary["flow_in"], summary["flow_out"]) == (1000, 400)
    assert summary["net_flow"] == summary["flow_in"] - summary["flow_out"]
    for period in body["periods"]:
        assert period["net_flow"] == pytest.approx(
            period["flow_in"] - period["flow_out"]
        )


# -- My groups --------------------------------------------------------------


def test_a_client_keeps_named_groups_of_their_accounts(maya, world):  # noqa: F811
    made = maya.post(
        GROUPS, json={"name": " Retirement ", "account_ids": [world["ira"].id]}
    )
    assert made.status_code == 201
    group = made.json()
    assert group["name"] == "Retirement" and group["account_ids"] == [world["ira"].id]

    renamed = maya.patch(f"{GROUPS}/{group['id']}", json={"name": "Long term"})
    both = maya.put(
        f"{GROUPS}/{group['id']}/accounts",
        json={"account_ids": [world["ira"].id, world["brokerage"].id]},
    )
    assert renamed.json()["name"] == "Long term"
    assert set(both.json()["account_ids"]) == {world["ira"].id, world["brokerage"].id}
    assert [g["name"] for g in maya.get(GROUPS).json()["groups"]] == ["Long term"]

    assert maya.delete(f"{GROUPS}/{group['id']}").status_code == 204
    assert maya.get(GROUPS).json()["groups"] == []


def test_a_group_name_is_used_once(maya):  # noqa: F811
    assert maya.post(GROUPS, json={"name": "Kids"}).status_code == 201
    assert maya.post(GROUPS, json={"name": "kids"}).status_code == 409


def test_a_group_holds_only_accounts_the_client_can_see(maya, db, world):  # noqa: F811
    refused = maya.post(
        GROUPS, json={"name": "Theirs", "account_ids": [world["trust"].id]}
    )
    assert refused.status_code == 404

    access = AccountAccess(client_id=world["maya"].id, account_id=world["trust"].id)
    db.add(access)
    db.commit()
    group = maya.post(
        GROUPS, json={"name": "Family", "account_ids": [world["trust"].id]}
    ).json()
    db.delete(access)
    db.commit()

    # Sharing withdrawn: the account drops out of the group.
    assert maya.get(GROUPS).json()["groups"][0]["account_ids"] == []
    assert group["account_ids"] == [world["trust"].id]


def test_one_clients_groups_are_out_of_anothers_reach(maya, db, world):  # noqa: F811
    group = maya.post(GROUPS, json={"name": "Mine"}).json()
    ravi = _browser_for(db, world["ravi"])

    assert ravi.get(GROUPS).json()["groups"] == []
    assert ravi.patch(f"{GROUPS}/{group['id']}", json={"name": "x"}).status_code == 404
    assert ravi.delete(f"{GROUPS}/{group['id']}").status_code == 404


def test_an_advisor_previewing_sees_the_groups_but_cannot_change_them(
    client, db, world  # noqa: F811
):
    # The advisor fixture signs every request in as the advisor, so the client's
    # group is made directly.
    AccountGroupService(db, world["maya"].id).create("Mine")
    preview = {"as_client": world["maya"].id}

    seen = client.get(GROUPS, params=preview).json()["groups"]
    changed = client.post(GROUPS, params=preview, json={"name": "Advisor's"})

    assert [g["name"] for g in seen] == ["Mine"]
    assert changed.status_code == 403
