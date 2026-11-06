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
