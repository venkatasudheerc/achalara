"""Live SnapTrade API tests — opt-in, read-only.

These are the only tests in the suite that touch a third-party API. They are
excluded from the default run (``addopts = -m "not live"`` in pytest.ini) and
skip themselves unless real credentials are present, so a plain ``pytest`` and
CI never reach the network.

Run them deliberately::

    export SNAPTRADE_TEST_USER_ID=<the userId you linked>
    venv/bin/pytest tests/integration/test_snaptrade_live.py -m live -v -s

Their purpose is not regression cover — payloads change outside our control,
so asserting exact values would make them flaky. They answer the questions
offline tests cannot: what a *real* brokerage actually returns. Each one
prints what it found, because the output is the point.

Read-only by construction: nothing here places an order, and the connector
raises on ``place_order`` while ``can_trade`` is False.

Rate limits are real — SnapTrade asks for >=24h between transaction calls per
account and <=4 background holdings calls per user per day. Do not loop these.
"""
import pytest

pytestmark = pytest.mark.live


def test_credentials_authenticate(live_snaptrade, live_snaptrade_user_id):
    """The configured keys are accepted by SnapTrade.

    Fails fast and clearly if the keys are wrong, so the richer tests below
    don't report a confusing error instead.
    """
    accounts = live_snaptrade.fetch_accounts(
        live_snaptrade_user_id,
        credentials=_creds(live_snaptrade_user_id),
    )
    print(f"\nSnapTrade returned {len(accounts)} account(s)")
    assert isinstance(accounts, list)


def test_accounts_map_onto_our_hierarchy(live_snaptrade, live_snaptrade_user_id):
    """Every linked account exposes what we need to map it to an Account.

    One brokerage login commonly exposes several accounts (brokerage, IRA,
    joint); each needs a stable ``external_ref`` to map against.
    """
    accounts = live_snaptrade.fetch_accounts(
        live_snaptrade_user_id, credentials=_creds(live_snaptrade_user_id)
    )
    if not accounts:
        pytest.skip(
            "No accounts linked yet — complete the Connection Portal flow first"
        )

    for account in accounts:
        print(
            f"  {account.external_ref}  {account.institution!r}  "
            f"{account.name!r}  number={account.account_number!r}"
        )
        # A missing external_ref would make the account unmappable.
        assert account.external_ref

    refs = [a.external_ref for a in accounts]
    assert len(refs) == len(set(refs)), "account refs must be unique to map reliably"


def test_transactions_map_to_trades(live_snaptrade, live_snaptrade_user_id):
    """Real activity maps cleanly onto NormalizedTrade.

    This is the test that validates the provisional mapping in
    ``_to_trade``/``_symbol_ticker`` against data we did not invent.
    """
    creds = _creds(live_snaptrade_user_id)
    accounts = live_snaptrade.fetch_accounts(live_snaptrade_user_id, credentials=creds)
    if not accounts:
        pytest.skip("No accounts linked yet")

    # One account under a login can still be mid initial sync and return
    # nothing, so use the first account that actually has trades.
    account, trades = None, []
    for candidate in accounts:
        trades = live_snaptrade.fetch_transactions(
            live_snaptrade_user_id, candidate.external_ref, credentials=creds
        )
        account = candidate
        if trades:
            break
    print(
        f"\n{len(trades)} trade(s) mapped from {account.institution} {account.name!r}"
    )

    if not trades:
        pytest.skip(
            "No BUY/SELL activity returned — the account may be new, or hold only "
            "non-trade activity (dividends/contributions), which we skip by design"
        )

    for trade in trades[:5]:
        print(
            f"  {trade.executed_at.date()}  {trade.action.value:4}  "
            f"{trade.symbol:12}  qty={trade.quantity}  px={trade.price}  "
            f"fee={trade.commission}"
        )

    for trade in trades:
        # Each of these would break ingestion or the performance timeline.
        assert trade.symbol, "symbol must resolve or the trade cannot be stored"
        assert trade.quantity > 0, "quantity must be positive (abs of signed units)"
        assert trade.price > 0
        assert trade.executed_at is not None
        assert trade.external_id
        assert trade.source == "snaptrade"

    # Chronological order is what ingestion assumes.
    dates = [t.executed_at for t in trades]
    assert dates == sorted(dates)


def test_external_ids_are_unique_within_an_account(
    live_snaptrade, live_snaptrade_user_id
):
    """The dedup key does not collapse distinct real trades.

    This is the open risk in the design: ``external_id`` is derived from
    (account, date, symbol, qty, price), so two genuinely separate fills of one
    order — same day, same price — would share a key and one would be dropped
    as a duplicate. A failure here means the key needs
    ``external_reference_id`` mixed in.
    """
    creds = _creds(live_snaptrade_user_id)
    accounts = live_snaptrade.fetch_accounts(live_snaptrade_user_id, credentials=creds)
    if not accounts:
        pytest.skip("No accounts linked yet")

    for account in accounts:
        trades = live_snaptrade.fetch_transactions(
            live_snaptrade_user_id, account.external_ref, credentials=creds
        )
        ids = [t.external_id for t in trades]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            for dup in duplicates:
                clashing = [t for t in trades if t.external_id == dup]
                print(f"\nCOLLISION on {dup}:")
                for t in clashing:
                    print(
                        f"  {t.raw.get('id')}  ref={t.raw.get('external_reference_id')}"
                    )
        assert not duplicates, (
            f"{len(duplicates)} dedup-key collision(s) in {account.name!r}: distinct "
            "trades share an external_id and would be silently dropped. Mix "
            "external_reference_id into snaptrade_external_id()."
        )
        print(f"  {account.name!r}: {len(ids)} trade(s), all keys unique")


def test_positions_map_to_holdings(live_snaptrade, live_snaptrade_user_id):
    """Real holdings map onto NormalizedPosition.

    Positions carry the security under ``instrument`` rather than ``symbol``,
    so this exercises a different path through the connector. Covers every
    account, since some under one login hold nothing.
    """
    creds = _creds(live_snaptrade_user_id)
    accounts = live_snaptrade.fetch_accounts(live_snaptrade_user_id, credentials=creds)
    if not accounts:
        pytest.skip("No accounts linked yet")

    positions = []
    for account in accounts:
        found = live_snaptrade.fetch_positions(
            live_snaptrade_user_id, account.external_ref, credentials=creds
        )
        print(f"\n{len(found)} position(s) in {account.name!r}")
        for position in found[:10]:
            print(
                f"  {position.symbol:12}  qty={position.quantity}  "
                f"avg_cost={position.avg_cost}  px={position.market_price}"
            )
        positions.extend(found)

    for position in positions:
        assert position.symbol, "position symbol must resolve"


def test_report_activity_types_present(live_snaptrade, live_snaptrade_user_id):
    """Inventory the raw activity types this brokerage emits.

    Informational, never failing. Reads the unfiltered feed straight from the
    SDK, because the connector drops non-trade types before anything here
    could see them — counting its output would only ever show BUY/SELL.
    """
    from collections import Counter

    creds = _creds(live_snaptrade_user_id)
    accounts = live_snaptrade.fetch_accounts(live_snaptrade_user_id, credentials=creds)
    if not accounts:
        pytest.skip("No accounts linked yet")

    api = live_snaptrade.client.account_information
    for account in accounts:
        counts: Counter = Counter()
        offset = 0
        while True:
            body = api.get_account_activities(
                account_id=account.external_ref,
                offset=offset,
                limit=1000,
                **creds.as_kwargs(),
            ).body
            rows = list(body.get("data") or [])
            counts.update(str(r.get("type")) for r in rows)
            offset += len(rows)
            if len(rows) < 1000:
                break
        print(f"\n{account.name!r}: {sum(counts.values())} activities")
        for name, count in counts.most_common():
            print(f"  {name:28} {count}")


def _creds(user_id: str):
    """Credentials for the Personal flow: a userId and no userSecret."""
    from app.connectors.snaptrade_connector import SnapTradeCredentials

    return SnapTradeCredentials(user_id=user_id)
