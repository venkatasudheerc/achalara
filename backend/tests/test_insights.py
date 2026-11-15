"""The Dashboard's nudges and insights: each rule, the checks every finding goes
through, and who may ask. Rules are tried against a stub of the portal so each
case states exactly what the accounts look like; the route test goes through the
real sign-in."""
from datetime import date, datetime, timedelta, timezone

from app.services.insights.base import Rule
from app.services.insights.registry import RULES
from app.services.insights.service import InsightService
from tests.test_roles import _browser, people  # noqa: F401  (fixture)

TODAY = date(2026, 11, 15)
NOW = datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc)
COMPLETE = {"state": "complete", "reasons": [], "download_from": None}


def account(id, kind, value, **more):
    owed = kind in ("credit_card", "mortgage", "car_loan", "loan")
    return {
        "id": id, "name": id, "display_name": None, "number_last4": None, "kind": kind,
        "owed": owed, "value": value, "cash": None, "shared": False, "owner_name": "Pat Example",
        "health": COMPLETE, "as_of": TODAY, "card": None, **more,
    }


def card(id, owed, **more):
    detail = {
        "credit_limit": 10000, "minimum_payment": 35, "next_payment_due_date": None,
        "is_overdue": False, "as_of": NOW, **more,
    }
    return account(id, "credit_card", -owed, card=detail)


def login(id, state="sharing", own=True, accounts=(), **more):
    return {
        "id": id, "institution": "Harbor Bank", "state": state, "own": own,
        "owner_name": "Sam Example", "consent_expires_at": None, "disabled_at": None,
        "accounts": list(accounts), "waiting_accounts": 0, **more,
    }


class Stub:
    def __init__(self, accounts, connections=(), home=None, tax=None):
        self._accounts, self._connections = accounts, list(connections)
        self._home = home if home is not None else {
            "total_value": 0, "concentrated": [], "top_holdings": [], "expiring_options": []}
        self._tax = tax or {"carried_losses": 0.0, "turning_long_term": []}

    def accounts(self):
        return self._accounts

    def connections(self):
        return {"connections": self._connections, "needs_sign_in": 0}

    def home(self):
        return self._home

    def tax_facts(self, today=None):
        return self._tax


def run(stub, rules=None):
    service = InsightService(stub, lambda ids: stub, today=TODAY, rules=rules)
    return service.respond()


def keys(findings):
    return [f["rule"] for f in findings]


# -- connections ------------------------------------------------------------

def test_a_login_that_stopped_is_a_must_do_for_its_owner_and_news_for_anyone_else():
    a = account("Checking", "checking", 900)
    since = datetime(2026, 11, 11, tzinfo=timezone.utc)
    mine = run(Stub([a], [login("L1", "needs_sign_in", True, [a], disabled_at=since)]))["nudges"][0]
    assert mine["must"] and mine["action"]["kind"] == "repair_login" and mine["action"]["login_id"] == "L1"
    assert "stopped sharing 1 account" in mine["title"] and "11 Nov" in mine["detail"]

    theirs = run(Stub([a], [login("L1", "needs_sign_in", False, [a], disabled_at=since)]))["nudges"][0]
    assert not theirs["must"] and theirs["action"] is None and "Sam signs in to it" in theirs["detail"]


def test_a_login_with_no_account_in_view_says_nothing():
    assert run(Stub([], [login("L1", "needs_sign_in", True, [])]))["nudges"] == []


def test_an_incomplete_record_is_a_must_do_for_the_owner_and_holds_back_what_is_built_on_it():
    sick = account("Brokerage", "taxable", 400000, health={
        "state": "incomplete", "reasons": ["Holdings differ since 2 Sep 2026."],
        "download_from": date(2026, 9, 2)})
    cash = account("Cash", "cash", 190000)
    out = run(Stub([sick, cash]))
    repair = out["nudges"][0]
    assert repair["rule"] == "record_incomplete" and repair["must"]
    assert "2 Sep" in repair["detail"] and repair["action"]["account_id"] == "Brokerage"
    # Idle cash counts the broker's cash too, so it waits for the record.
    assert "idle_cash" not in keys(out["nudges"])

    shared = {**sick, "shared": True}
    other = run(Stub([shared, cash]))["nudges"][0]
    assert other["action"] is None and not other["must"] and "Pat can repair it" in other["detail"]


def test_consent_ending_and_accounts_waiting_are_the_owners_to_act_on():
    a = account("Savings", "savings", 5000)
    brk = account("Brk", "taxable", 500000, cash=0)  # so cash is not a tenth of the whole
    soon = NOW + timedelta(days=9)
    ending = login("L1", "consent_ending", True, [a], consent_expires_at=soon)
    waiting = login("L2", "sharing", True, [], waiting_accounts=2)
    others = login("L3", "consent_ending", False, [a], consent_expires_at=soon, waiting_accounts=3)
    out = run(Stub([a, brk], [ending, waiting, others]))["nudges"]
    assert sorted(keys(out)) == ["accounts_waiting", "consent_ending"]
    by = {f["rule"]: f for f in out}
    assert by["consent_ending"]["action"]["kind"] == "repair_login"
    assert by["accounts_waiting"]["title"] == "Harbor Bank has 2 accounts not added yet"
    assert by["accounts_waiting"]["action"]["view"] == "connections"
    assert by["accounts_waiting"]["action"]["label"] == "Review"


# -- cards ------------------------------------------------------------------

def test_a_payment_due_this_week_names_the_minimum_and_what_checking_holds():
    visa = card("Visa", 1240, next_payment_due_date=TODAY + timedelta(days=4))
    far = card("Far", 500, next_payment_due_date=TODAY + timedelta(days=20))
    paid = card("Paid", 0, next_payment_due_date=TODAY + timedelta(days=2))
    out = run(Stub([visa, far, paid, account("Chk", "checking", 912)]))["nudges"]
    assert [f["rule"] for f in out] == ["card_due_soon"]
    due = out[0]
    assert due["title"] == "A card payment is due in 4 days"
    assert due["visual"]["type"] == "countdown" and due["visual"]["days"] == 4
    assert "$1,240 owed, minimum $35" in due["detail"] and "hold $912" in due["detail"]
    # One account has no Accounts tab: the card is read on its own Dashboard.
    assert due["action"]["sel"] == "account:Visa" and due["action"]["view"] == "dashboard"


def test_an_overdue_card_is_said_once_and_a_stale_figure_is_not_acted_on():
    overdue = card("Visa", 300, is_overdue=True, next_payment_due_date=TODAY - timedelta(days=2))
    out = run(Stub([overdue]))["nudges"]
    assert keys(out) == ["card_overdue"]

    stale = card("Old", 300, is_overdue=True, as_of=NOW - timedelta(days=5))
    assert run(Stub([stale]))["nudges"] == []


def test_cards_owed_of_limits_warns_only_past_half():
    calm = run(Stub([card("A", 1000), card("B", 1000)]))["insights"][0]
    assert calm["title"] == "You owe 10% of your card limits"
    assert calm["visual"]["warn"] is False and "None is past half" in calm["detail"]

    heavy = run(Stub([card("A", 6000)]))["insights"][0]
    assert heavy["visual"]["warn"] is True and "1 is past half" in heavy["detail"]
    assert run(Stub([account("Chk", "checking", 10)]))["insights"] == []


# -- cash and the balance sheet --------------------------------------------

def test_cash_above_a_tenth_of_what_is_held_is_a_nudge_and_a_tenth_exactly_is_not():
    over = [account("Chk", "checking", 12000), account("Brk", "taxable", 88000, cash=0)]
    out = run(Stub(over))["nudges"]
    assert keys(out) == ["idle_cash"] and out[0]["title"] == "$12,000 is in cash: 12% of what you own"
    assert [p["label"] for p in out[0]["visual"]["parts"]] == [
        "Checking, savings and cash accounts", "Invested"]

    exactly = [account("Chk", "checking", 10000), account("Brk", "taxable", 90000, cash=0)]
    assert run(Stub(exactly))["nudges"] == []
    # A few dollars of a tiny household is never worth a mention.
    assert run(Stub([account("Chk", "checking", 500), account("Brk", "taxable", 100, cash=0)]))["nudges"] == []


def test_cash_inside_a_brokerage_counts_once_and_is_not_added_to_a_cash_accounts_own_value():
    accounts = [account("Brk", "taxable", 100000, cash=20000), account("Cash", "cash", 5000, cash=5000)]
    finding = run(Stub(accounts))["nudges"][0]
    assert finding["title"] == "$25,000 is in cash: 24% of what you own"
    assert [(p["label"], p["value"]) for p in finding["visual"]["parts"]] == [
        ("Checking, savings and cash accounts", 5000), ("Cash at brokerages", 20000), ("Invested", 80000)]


def test_assets_and_owed_needs_both_sides_and_splits_what_is_owed():
    accounts = [account("Brk", "taxable", 900000, cash=0), account("Mortgage", "mortgage", -300000),
                account("Visa", "credit_card", -3000)]
    finding = run(Stub(accounts))["insights"][0]
    assert finding["rule"] == "assets_and_owed"
    assert finding["title"] == "You owe $303,000: 34% of the $900,000 you own"
    assert [(p["label"], p["value"]) for p in finding["visual"]["parts"]] == [
        ("Mortgage", 300000), ("Credit cards", 3000)]
    assert "assets_and_owed" not in keys(run(Stub([account("Brk", "taxable", 900000, cash=0)]))["insights"])
    assert "assets_and_owed" not in keys(run(Stub([account("Visa", "credit_card", -3000)]))["insights"])


# -- investments ------------------------------------------------------------

def home(**more):
    return {
        "total_value": 1000000, "concentrated": [], "top_holdings": [],
        "expiring_options": [], **more,
    }


def test_a_holding_over_a_fifth_is_a_fact_with_no_action():
    brk = account("Brk", "taxable", 1000000, cash=0)
    top = {"symbol": "NVDA", "value": 210000, "share": 0.21}
    nxt = {"symbol": "AAPL", "value": 70000, "share": 0.07}
    out = run(Stub([brk], home=home(concentrated=[top], top_holdings=[top, nxt])))["insights"]
    finding = next(f for f in out if f["rule"] == "concentration")
    assert finding["title"] == "One holding, NVDA, is 21% of what you hold"
    assert finding["action"] is None and finding["detail"] == "The next largest is 7%."
    assert finding["visual"]["type"] == "meter" and finding["foot"] == "At live prices"
    assert "concentration" not in keys(run(Stub([brk], home=home()))["insights"])


def test_options_about_to_expire_say_how_far_the_shares_are_from_each_strike():
    brk = account("Brk", "taxable", 1000000, cash=0)
    options = [
        {"underlying": "AAPL", "kind": "call", "strike": 230.0, "written": True, "contracts": 2,
         "days": 6, "above_strike_pct": -0.018},
        {"underlying": "MSFT", "kind": "put", "strike": 400.0, "written": False, "contracts": 1,
         "days": 9, "above_strike_pct": None},
    ]
    finding = run(Stub([brk], home=home(expiring_options=options)))["insights"][0]
    assert finding["title"] == "2 options expire within two weeks"
    assert finding["visual"]["days"] == 6
    assert finding["visual"]["rows"] == [
        {"label": "AAPL 230 call · written · 2", "value": "1.8% below strike"},
        {"label": "MSFT 400 put · bought · 1", "value": "no live price"},
    ]


def test_tax_facts_read_taxable_accounts_only_and_only_what_is_near():
    taxable = account("Brk", "taxable", 500000, cash=0)
    ira = account("IRA", "retirement", 500000, cash=0)
    tax = {"carried_losses": 6120.0, "turning_long_term": [
        {"symbol": "MSFT", "date": TODAY + timedelta(days=27)},
        {"symbol": "COST", "date": TODAY + timedelta(days=34)},
        {"symbol": "AVGO", "date": TODAY + timedelta(days=200)},
    ]}
    out = run(Stub([taxable, ira], home=home(), tax=tax))["insights"]
    by = {f["rule"]: f for f in out}
    assert by["turning_long_term"]["title"] == "MSFT shares turn long-term in 27 days"
    assert by["turning_long_term"]["visual"]["rows"] == [{"label": "COST", "value": "19 Dec"}]
    assert by["carried_losses"]["visual"]["text"] == "$6,120"
    # With only a retirement account in view there is nothing to tax.
    only_ira = run(Stub([ira], home=home()))["insights"]
    assert not {"turning_long_term", "carried_losses"} & set(keys(only_ira))


# -- the checks ---------------------------------------------------------------

def test_order_is_must_first_then_most_pressing_and_a_failing_rule_is_skipped():
    class Boom(Rule):
        id = "boom"

        def find(self, ctx):
            raise RuntimeError("one rule's trouble")

    visa = card("Visa", 1240, next_payment_due_date=TODAY + timedelta(days=4))
    chk = account("Chk", "checking", 900)
    brk = account("Brk", "taxable", 50000, cash=20000)
    stopped = login("L1", "needs_sign_in", True, [chk])
    out = run(Stub([visa, chk, brk], [stopped], home=home()), rules=[Boom(), *RULES])
    assert keys(out["nudges"]) == ["login_needs_sign_in", "card_due_soon", "idle_cash"]
    assert out["nudges"][0]["must"] and not out["nudges"][1]["must"]


def test_nothing_to_say_is_two_empty_lists():
    assert run(Stub([])) == {"nudges": [], "insights": []}


# -- through the real route ---------------------------------------------------

def test_the_route_answers_for_the_viewer_only_and_a_preview_sees_what_the_client_does(db, people):  # noqa: F811
    pat = _browser("login-pat@example.com")
    body = pat.get("/api/v1/portal/insights")
    assert body.status_code == 200
    assert set(body.json()) == {"nudges", "insights"}

    preview = _browser("ben@example.com").get(
        "/api/v1/portal/insights", params={"as_client": people["pat"].id})
    assert preview.status_code == 200

    # An account that is not in view is the same answer as one that does not exist.
    assert pat.get("/api/v1/portal/insights", params={"account_ids": people["Lee brokerage"].id}).status_code == 404
    assert pat.get("/api/v1/portal/insights", params={"account_ids": people["Pat brokerage"].id}).status_code == 200
    # An advisor cannot ask about someone else's client.
    assert _browser("ben@example.com").get(
        "/api/v1/portal/insights", params={"as_client": people["lee"].id}).status_code == 404
