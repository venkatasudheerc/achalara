"""Alerts — a message to the advisor when something starts or stops needing a look.

Sent through a Telegram bot when one is configured (``TELEGRAM_BOT_TOKEN`` and
``TELEGRAM_CHAT_ID``); otherwise nothing is sent and nothing fails. A message
leaves the app for a third party, so it carries only the wording the status
service marks as safe for that: never a client's or an account's name.
"""
import json
import logging
import urllib.error
import urllib.request
from typing import List, Optional, Set

from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10


def configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def _post(token: str, chat_id: str, text: str) -> None:
    """Hand one message to Telegram. Raises when it is not accepted."""
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        response.read()


def send(text: str) -> bool:
    """Send a message if alerts are configured; whether it went.

    Never raises: an alert that cannot be delivered must not break the job
    that wanted to raise it. The token is part of the address, so a failure is
    logged without it.
    """
    if not configured():
        return False
    try:
        _post(settings.telegram_bot_token, settings.telegram_chat_id, text)
        return True
    except urllib.error.HTTPError as exc:
        logger.warning("Telegram did not accept an alert (HTTP %s)", exc.code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("An alert could not be sent: %s", type(exc).__name__)
    return False


def _site() -> str:
    origins = settings.cors_origins_list
    return origins[0] if origins else ""


def _message(heading: str, lines: List[str]) -> str:
    body = "\n".join(f"• {line}" for line in lines)
    link = f"\n\n{_site()}/app/status" if _site() else ""
    return f"Achalara: {heading}\n{body}{link}"


class StatusWatch:
    """Remembers what needed a look last time, and says what changed.

    Kept in memory: after a restart the first reading reports whatever is
    open then, once.
    """

    def __init__(self):
        self._known: Optional[Set[str]] = None

    def evaluate(self, db: Session) -> List[str]:
        """Compare the status with the last reading; the messages sent."""
        from app.services.status_service import StatusService

        current = list(StatusService(db).status()["alert_lines"])
        known = self._known if self._known is not None else set()
        appeared = [line for line in current if line not in known]
        cleared = [line for line in known if line not in current]
        self._known = set(current)

        messages = []
        if appeared:
            messages.append(_message("needs a look", appeared))
        if cleared:
            heading = "resolved" if current else "resolved, all clear"
            messages.append(_message(heading, sorted(cleared)))
        return [text for text in messages if send(text)]


watch = StatusWatch()


def run_status_watch(db: Session) -> None:
    """Called by the scheduler, and after anything likely to change the status."""
    if configured():
        watch.evaluate(db)
