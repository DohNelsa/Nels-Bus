"""
Signed digital ticket tokens (QR payloads) using Django's signing framework.
"""

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

TICKET_SALT = "garanti.ticket.v1"
CHECKOUT_SALT = "garanti.checkout.v1"


def _signing_key():
    raw = getattr(settings, "TICKET_SIGNING_SECRET", None)
    if raw and str(raw).strip():
        return str(raw).strip()
    return settings.SECRET_KEY


def _signer() -> TimestampSigner:
    return TimestampSigner(key=_signing_key(), salt=TICKET_SALT)


def sign_booking_group_ticket(booking_group_id: int) -> str:
    return _signer().sign(str(int(booking_group_id)))


def verify_ticket_token(token: str):
    """
    Returns booking group id if the token is valid and not expired, else None.
    """
    if not token or not str(token).strip():
        return None
    max_age = int(getattr(settings, "TICKET_MAX_AGE_SECONDS", 120 * 24 * 3600))
    try:
        return int(_signer().unsign(token, max_age=max_age))
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None


def _checkout_signer() -> TimestampSigner:
    return TimestampSigner(key=_signing_key(), salt=CHECKOUT_SALT)


def sign_checkout_token(booking_group_id: int) -> str:
    """Short-lived token so guests can open payment pages if the session cookie is missing."""
    return _checkout_signer().sign(str(int(booking_group_id)))


def verify_checkout_token(token: str):
    """Returns booking group id if valid, else None."""
    if not token or not str(token).strip():
        return None
    max_age = int(getattr(settings, "CHECKOUT_MAX_AGE_SECONDS", 2 * 3600))
    try:
        return int(_checkout_signer().unsign(str(token).strip(), max_age=max_age))
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None
