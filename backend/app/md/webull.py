"""Webull's market-data endpoints, as the market-data jobs use them.

Signs requests the same way as the existing client, with each endpoint paced
at about half the lowest limit Webull documents for it, so these jobs leave
room for the live prices clients see. A refusal (HTTP 429) stops the job for
the night: ``WebullRefused`` is raised and nothing retries in a loop, because
Webull may block an address that keeps going past its limit.
"""
import http.client
import json
import time
import urllib.parse
from typing import Dict, Optional, Set

from app.md.config import settings
from app.utils.webull_signing import HOST, signed_headers

# Seconds between requests to one endpoint.
_FUNDAMENTALS_PACE = 2.0  # 30 a minute; Webull documents 60 for some of these
_DEFAULT_PACE = 0.5  # 120 a minute; Webull documents 300


class WebullRefused(Exception):
    """Webull answered 429 (too many requests): stop for now."""


class WebullError(Exception):
    pass


class WebullUnreachable(WebullError):
    """No answer: a timeout, a dropped connection or a reply that was not JSON."""


class WebullInvalidSymbols(WebullError):
    """Webull refused the whole request because it does not know some symbols."""

    def __init__(self, path: str, symbols: Set[str]):
        super().__init__(f"{path}: unknown symbols {sorted(symbols)}")
        self.symbols = symbols


def _invalid_symbols(raw: bytes) -> Optional[Set[str]]:
    """The symbols an INVALID_SYMBOL reply names, e.g. ``... [ABC, XYZ].``"""
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("error_code") != "INVALID_SYMBOL":
        return None
    message = str(body.get("message") or "")
    start, end = message.find("["), message.find("]")
    if start == -1 or end <= start:
        return None
    return {
        part.strip() for part in message[start + 1 : end].split(",") if part.strip()
    }


class WebullClient:
    def __init__(self):
        self._last: Dict[str, float] = {}
        self.requests = 0

    def configured(self) -> bool:
        return bool(settings.webull_app_key and settings.webull_app_secret)

    def _pace(self, path: str) -> None:
        gap = _FUNDAMENTALS_PACE if "/fundamentals/" in path else _DEFAULT_PACE
        wait = self._last.get(path, 0) + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last[path] = time.monotonic()

    def get(self, path: str, query: Optional[dict] = None):
        return self._send(
            "GET", path, {k: v for k, v in (query or {}).items() if v is not None}, None
        )

    def post(self, path: str, body: dict):
        return self._send("POST", path, {}, json.dumps(body, separators=(",", ":")))

    def _send(self, method: str, path: str, query: dict, body: Optional[str]):
        self._pace(path)
        headers = signed_headers(
            settings.webull_app_key,
            settings.webull_app_secret,
            HOST,
            path,
            query,
            body,
            version="v3",
        )
        if body:
            headers["Content-Type"] = "application/json"
        url = path + ("?" + urllib.parse.urlencode(query) if query else "")
        conn = http.client.HTTPSConnection(HOST, timeout=30)
        self.requests += 1
        try:
            conn.request(method, url, body, headers)
            response = conn.getresponse()
            raw = response.read()
        except (OSError, http.client.HTTPException) as exc:
            raise WebullUnreachable(f"{path}: {type(exc).__name__}") from exc
        finally:
            conn.close()
        if response.status == 429:
            raise WebullRefused(path)
        if response.status != 200:
            invalid = _invalid_symbols(raw)
            if invalid:
                raise WebullInvalidSymbols(path, invalid)
            raise WebullError(f"{path}: HTTP {response.status}")
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise WebullUnreachable(f"{path}: reply was not JSON") from exc
