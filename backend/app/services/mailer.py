"""Email to a client: the one-time link that sets or resets their password.

Sent through Resend when it is configured (``RESEND_API_KEY`` and
``MAIL_FROM``); otherwise nothing is sent and the advisor passes the link on
by hand, as before. The message carries the link and nothing about the
client's accounts.
"""
import html
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings
from app.models.user import PURPOSE_INVITE

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15
_ENDPOINT = "https://api.resend.com/emails"
_ZONE = ZoneInfo("America/New_York")
_USER_AGENT = "achalara-mailer/1.0"


def site() -> str:
    """The address clients reach the app at, which a link is built on."""
    origins = settings.cors_origins_list
    return origins[0].rstrip("/") if origins else ""


def configured() -> bool:
    return bool(settings.resend_api_key and settings.mail_from and site())


def _request(api_key: str, message: dict) -> urllib.request.Request:
    return urllib.request.Request(
        _ENDPOINT,
        data=json.dumps(message).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # The service turns away a request that does not say what is
            # calling, which is what Python's own default amounts to.
            "User-Agent": _USER_AGENT,
        },
    )


def _post(api_key: str, message: dict) -> None:
    """Hand one message to Resend. Raises when it is not accepted."""
    with urllib.request.urlopen(
        _request(api_key, message), timeout=_TIMEOUT_SECONDS
    ) as response:
        response.read()


def link_message(
    name: str, email: str, purpose: str, path: str, expires_at: datetime
) -> dict:
    """The message that carries a one-time link to the person it is for."""
    url = f"{site()}{path}"
    until = expires_at.astimezone(_ZONE).strftime("%B %-d at %-I:%M %p US Eastern")
    first = (name or "").split(" ")[0] or "there"
    if purpose == PURPOSE_INVITE:
        subject = "Set up your Achalara sign-in"
        opening = (
            "Your Achalara account is ready. Use the link below to choose a "
            "password and sign in."
        )
    else:
        subject = "Choose a new Achalara password"
        opening = "Use the link below to choose a new password for Achalara."
    closing = (
        f"The link works once and expires on {until}. You will sign in with "
        f"{email}. If you were not expecting this, you can ignore it."
    )
    text = f"Hello {first},\n\n{opening}\n\n{url}\n\n{closing}\n"
    markup = (
        f"<p>Hello {html.escape(first)},</p><p>{html.escape(opening)}</p>"
        f'<p><a href="{html.escape(url)}">{html.escape(url)}</a></p>'
        f"<p>{html.escape(closing)}</p>"
    )
    return {
        "from": settings.mail_from,
        "to": [email],
        "subject": subject,
        "text": text,
        "html": markup,
    }


def _refusal(error: urllib.error.HTTPError) -> str:
    """The service's own name for why it refused, e.g. ``validation_error``.

    Only the name: its longer message can repeat the recipient's address.
    """
    try:
        name = json.loads(error.read()).get("name")
    except Exception:  # noqa: BLE001
        return "no reason given"
    return name if isinstance(name, str) and name.isidentifier() else "no reason given"


def send(message: dict) -> bool:
    """Send a message if email is configured; whether it was accepted.

    Never raises, and never logs the key, the recipient or the link: the
    address is a client's and the link is a way in.
    """
    if not configured():
        return False
    try:
        _post(settings.resend_api_key, message)
        return True
    except urllib.error.HTTPError as exc:
        logger.warning(
            "The mail service did not accept a message (HTTP %s, %s)",
            exc.code,
            _refusal(exc),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("A message could not be sent: %s", type(exc).__name__)
    return False
