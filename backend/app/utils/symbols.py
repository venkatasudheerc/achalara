"""How one ticker is spelled in each place.

The sources disagree about share classes, and the app's own tables keep the
brokerage's spelling. Anything that crosses from one to another goes through
these, so there is one conversion:

    Brokerage, Webull, iShares   BRK B
    SEC                          BRK-B
    OpenFIGI                     BRK/B
    md (stored)                  BRK.B
"""
import re

# A holding the institution names but gives no ticker (a 401k's target-date trust,
# a 529 portfolio) is kept under its name with this in front: "#TARGET RETIRE 2050
# TRUST". It is a real holding, counted and checked like any other, but there is
# nothing to ask a price source or market data about, so they are left out of
# every request to one (``quotable``, ``held_symbols``). ``~`` is another thing:
# a security that no longer trades, which is not compared.
NAMED_PREFIX = "#"
_NAMED_LIMIT = 50  # the symbol columns


def named_symbol(name: str) -> str:
    """The symbol a ticker-less holding is kept under: its name in capitals,
    letters, digits and single spaces, with ``#`` in front."""
    plain = re.sub(r"[^A-Z0-9]+", " ", (name or "").upper()).strip()
    return (NAMED_PREFIX + plain)[:_NAMED_LIMIT].rstrip()


def is_named_symbol(symbol: str) -> bool:
    """Whether ``symbol`` is a name kept for a holding with no ticker."""
    return (symbol or "").startswith(NAMED_PREFIX)


def app_symbol(raw: str) -> str:
    """``md``'s spelling: ``BRK B`` / ``BRK/B`` / ``BRK-B`` -> ``BRK.B``.

    Trades from sheets may carry an exchange prefix (``NASDAQ:AAPL``), which is
    not part of the ticker.
    """
    symbol = (raw or "").split(":")[-1].strip().upper()
    return re.sub(r"[ /-]", ".", symbol)


def webull_symbol(raw: str) -> str:
    """Webull's spelling. It answers ``INVALID_SYMBOL`` to ``BRK.B``."""
    return app_symbol(raw).replace(".", " ")


def figi_symbol(raw: str) -> str:
    """OpenFIGI's spelling."""
    return app_symbol(raw).replace(".", "/")
