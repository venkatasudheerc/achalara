"""Whether an email address's domain can receive mail at all.

Asked of the public DNS, so a made-up domain is turned away before anything
is kept. When DNS cannot answer in time the address is given the benefit of
the doubt: a slow lookup must not stop a real person.
"""
import logging

from email_validator import EmailNotValidError, EmailUndeliverableError, validate_email

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 4


def receives_mail(email: str) -> bool:
    try:
        validate_email(email, check_deliverability=True, timeout=_TIMEOUT_SECONDS)
    except EmailUndeliverableError:
        return False
    except EmailNotValidError:
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not check an email domain: %s", type(exc).__name__)
    return True
