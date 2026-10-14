"""Requests for an invitation, left by visitors on the public page.

This is the one place a stranger can write to the database, so it is guarded:
a limit on how often one address may ask and on how many requests a day are
kept at all, a hidden field that only a script fills in, and no reply that
tells a sender which of these stopped them. Nothing is ever sent to the email
a visitor types, or the form would be a way to write to other people.
"""
import logging
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.invitation_request import (
    STATUS_NEW,
    STATUSES,
    InvitationRequest,
)
from app.services import alerts

logger = logging.getLogger(__name__)

# One network address may ask this often.
PER_SENDER = 3
PER_SENDER_WINDOW = timedelta(hours=1)
# However many senders there are, no more than this are kept in a day.
PER_DAY = 40
# A second request from the same email while the first is unanswered adds nothing.
REPEAT_WINDOW = timedelta(days=7)

_lock = threading.Lock()
_by_sender: Dict[str, Deque[datetime]] = {}
_today: Deque[datetime] = deque()


def forget() -> None:
    """Clear the counts kept in memory (for tests)."""
    with _lock:
        _by_sender.clear()
        _today.clear()


def _allowed(sender: str, now: datetime) -> bool:
    """Count this attempt against the limits; whether it may be kept."""
    with _lock:
        while _today and now - _today[0] > timedelta(days=1):
            _today.popleft()
        recent = _by_sender.setdefault(sender, deque())
        while recent and now - recent[0] > PER_SENDER_WINDOW:
            recent.popleft()
        if len(recent) >= PER_SENDER or len(_today) >= PER_DAY:
            return False
        recent.append(now)
        _today.append(now)
        # Senders seen long ago are dropped so the record cannot grow without end.
        for key in [k for k, v in _by_sender.items() if not v]:
            del _by_sender[key]
        return True


class InvitationService:
    def __init__(self, db: Session):
        self.db = db

    def submit(
        self,
        name: str,
        email: str,
        phone: str,
        note: str,
        sender: str,
        trap: Optional[str] = None,
    ) -> bool:
        """Keep a visitor's request; whether it was kept.

        ``trap`` is the form's hidden field: a person never sees it, so
        anything in it marks a script. The caller answers the visitor the same
        way whatever this returns.
        """
        now = datetime.now(timezone.utc)
        if trap:
            return False
        if not _allowed(sender, now):
            logger.warning("An invitation request was turned away by the limits")
            return False

        email = email.strip().lower()
        waiting = (
            self.db.query(InvitationRequest)
            .filter(
                InvitationRequest.email == email,
                InvitationRequest.status == STATUS_NEW,
                InvitationRequest.created_at >= now - REPEAT_WINDOW,
            )
            .first()
        )
        if waiting is not None:
            return False

        self.db.add(InvitationRequest(name=name, email=email, phone=phone, note=note))
        self.db.commit()
        # The status page now says a request is waiting; tell the adviser at once
        # instead of at the next look. The alert names no one.
        try:
            alerts.run_status_watch(self.db)
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.warning("Status watch after an invitation request failed: %s", exc)
        return True

    def requests(self) -> List[InvitationRequest]:
        """Every request, those still waiting first, newest first within each."""
        rows = (
            self.db.query(InvitationRequest)
            .order_by(InvitationRequest.created_at.desc())
            .all()
        )
        return sorted(rows, key=lambda row: row.status != STATUS_NEW)

    def waiting(self) -> int:
        return (
            self.db.query(InvitationRequest)
            .filter(InvitationRequest.status == STATUS_NEW)
            .count()
        )

    def set_status(self, request_id: str, status: str) -> InvitationRequest:
        if status not in STATUSES:
            raise ValueError(f"Status must be one of {', '.join(STATUSES)}")
        row = (
            self.db.query(InvitationRequest)
            .filter(InvitationRequest.id == request_id)
            .first()
        )
        if row is None:
            raise LookupError("Request not found")
        row.status = status
        row.handled_at = None if status == STATUS_NEW else datetime.now(timezone.utc)
        self.db.commit()
        return row
