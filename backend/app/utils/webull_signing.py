"""Signing a request to Webull, shared by the app's client and the md jobs."""
import base64
import hashlib
import hmac
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Optional

HOST = "api.webull.com"


def signature(
    app_key: str,
    app_secret: str,
    host: str,
    path: str,
    query_params: dict,
    body_string: Optional[str],
    timestamp: str,
    nonce: str,
) -> str:
    """The HMAC-SHA1 signature Webull expects."""
    signing_headers = {
        "x-app-key": app_key,
        "x-timestamp": timestamp,
        "x-signature-algorithm": "HMAC-SHA1",
        "x-signature-version": "1.0",
        "x-signature-nonce": nonce,
        "host": host,
    }

    all_params = {**query_params, **signing_headers}
    str1 = "&".join(f"{k}={all_params[k]}" for k in sorted(all_params))

    if body_string:
        str2 = hashlib.md5(body_string.encode("utf-8")).hexdigest().upper()
        str3 = f"{path}&{str1}&{str2}"
    else:
        str3 = f"{path}&{str1}"

    encoded_string = urllib.parse.quote(str3, safe="")
    signing_key = f"{app_secret}&"

    return base64.b64encode(
        hmac.new(
            signing_key.encode("utf-8"),
            encoded_string.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")


def signed_headers(
    app_key: str,
    app_secret: str,
    host: str,
    path: str,
    query_params: Optional[dict] = None,
    body_string: Optional[str] = None,
    version: str = "v2",
) -> dict:
    """The headers for one signed request."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = uuid.uuid4().hex
    return {
        "Accept": "application/json",
        "x-app-key": app_key,
        "x-timestamp": timestamp,
        "x-signature": signature(
            app_key,
            app_secret,
            host,
            path,
            query_params or {},
            body_string,
            timestamp,
            nonce,
        ),
        "x-signature-algorithm": "HMAC-SHA1",
        "x-signature-version": "1.0",
        "x-signature-nonce": nonce,
        "x-version": version,
    }
