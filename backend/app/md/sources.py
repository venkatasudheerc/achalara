"""Where index membership files come from, and how they are fetched."""
import urllib.request
from dataclasses import dataclass
from typing import Callable

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)
_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class FundFile:
    source: str  # ishares | ssga
    name: str  # the fund's ticker
    url: str


# The funds whose daily holdings stand in for each index. iShares' plain
# "latest holdings" address answers scripts; its other download address does not.
FUND_FILES = {
    "IVV": FundFile(
        "ishares",
        "IVV",
        "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/latest-holdings.csv",
    ),
    "IWB": FundFile(
        "ishares",
        "IWB",
        "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/latest-holdings.csv",
    ),
    "IWM": FundFile(
        "ishares",
        "IWM",
        "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/latest-holdings.csv",
    ),
    # State Street's S&P 500 fund: a second, independent copy used to check IVV.
    "SPY": FundFile(
        "ssga",
        "SPY",
        "https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx",
    ),
}


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return response.read()


# Replaced in tests; nothing in the test suite reaches the network.
Fetch = Callable[[str], bytes]
fetch: Fetch = download
