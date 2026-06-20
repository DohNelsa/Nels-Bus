"""
WhatsApp booking notifications via Twilio WhatsApp API (or mock in dev).
"""

import hashlib
import logging
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

from .booking_receipt import (
    build_booking_confirmation_message,
    format_departure_parts,
    validate_receipt_message,
)
from .phone_utils import normalize_cameroon_phone
from .twilio_config import validate_twilio_whatsapp_credentials

logger = logging.getLogger(__name__)


def booking_group_whatsapp_phone(booking_group) -> str:
    """Phone used for WhatsApp — booking form number first, then passenger profile."""
    raw = (getattr(booking_group, "customer_phone", "") or "").strip()
    if not raw and getattr(booking_group, "passenger", None):
        raw = (getattr(booking_group.passenger, "phone", "") or "").strip()
    phone = normalize_cameroon_phone(raw)
    return phone if phone and phone.startswith("+237") else ""


def _whatsapp_address(e164: str) -> str:
    phone = (e164 or "").strip()
    if not phone:
        return ""
    if phone.lower().startswith("whatsapp:"):
        return phone
    return f"whatsapp:{phone}"


def build_whatsapp_send_url(phone_e164: str, message: str) -> str:
    """Public wa.me link — opens WhatsApp with pre-filled message (staff handoff)."""
    digits = "".join(ch for ch in (phone_e164 or "") if ch.isdigit())
    return f"https://wa.me/{digits}?text={quote(message or '')}"


def prepare_booking_whatsapp_handoff(booking_group) -> tuple[str | None, str | None]:
    """
    Build wa.me URL for staff to send confirmation manually.
    Persists receipt code on the booking before redirect.
    """
    phone = booking_group_whatsapp_phone(booking_group)
    if not phone:
        return None, "No valid Cameroon WhatsApp number on this booking."

    try:
        bg = (
            type(booking_group)
            .objects.select_related("passenger", "schedule", "schedule__bus", "schedule__route")
            .prefetch_related("bookings")
            .get(pk=booking_group.pk)
        )
    except Exception as exc:
        logger.exception("Could not reload booking group for WhatsApp handoff: %s", exc)
        return None, str(exc)

    if bg.whatsapp_receipt_code:
        receipt_code = bg.whatsapp_receipt_code
        _, msg = build_booking_confirmation_message(bg, receipt_code=receipt_code)
    else:
        receipt_code, msg = build_booking_confirmation_message(bg)

    bg.whatsapp_receipt_code = receipt_code
    bg.whatsapp_message_hash = hashlib.sha256(msg.encode("utf-8")).hexdigest()
    bg.whatsapp_error_message = None
    if bg.whatsapp_status == "FAILED":
        bg.whatsapp_status = "NOT_SENT"
    bg.save(
        update_fields=[
            "whatsapp_receipt_code",
            "whatsapp_message_hash",
            "whatsapp_error_message",
            "whatsapp_status",
        ]
    )

    return build_whatsapp_send_url(phone, msg), None


def send_whatsapp(to_number: str, message: str) -> tuple[bool, str | None]:
    """
    Send a WhatsApp message to `to_number` (Cameroon E.164, e.g. +237699123456).
    """
    if not to_number:
        return False, "Missing destination phone number."

    if not getattr(settings, "WHATSAPP_ENABLED", False):
        logger.info("WhatsApp disabled. Would send to=%s message=%s", to_number, message)
        return False, "WhatsApp is disabled (WHATSAPP_ENABLED is False)."

    provider = getattr(settings, "WHATSAPP_PROVIDER", "mock")
    to_addr = _whatsapp_address(to_number)

    if provider == "mock":
        logger.info("MOCK WhatsApp to=%s message=%s", to_addr, message)
        return True, None

    if provider == "twilio":
        try:
            from twilio.rest import Client  # type: ignore
        except Exception as exc:
            logger.exception("Twilio selected for WhatsApp but import failed: %s", exc)
            return False, f"Twilio import failed: {exc}"

        account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
        auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
        from_number = getattr(settings, "TWILIO_WHATSAPP_FROM", "")

        config_error = validate_twilio_whatsapp_credentials(
            account_sid=account_sid,
            auth_token=auth_token,
            whatsapp_from=from_number,
        )
        if config_error:
            logger.warning("Twilio WhatsApp config invalid: %s", config_error)
            return False, config_error

        from_addr = _whatsapp_address(from_number)

        try:
            client = Client(account_sid, auth_token)
            msg = client.messages.create(body=message, from_=from_addr, to=to_addr)
            if bool(getattr(msg, "sid", None)):
                return True, None
            return False, "Twilio did not return a message SID."
        except Exception as exc:
            logger.exception("Twilio WhatsApp send failed to=%s: %s", to_addr, exc)
            err_text = str(exc)
            if "401" in err_text or "authentication error" in err_text.lower():
                return False, (
                    "Twilio authentication failed (HTTP 401). Check TWILIO_ACCOUNT_SID (starts with AC) "
                    "and TWILIO_AUTH_TOKEN in Nelsaproject/.env match your Twilio Console, then restart the server."
                )
            return False, f"Twilio WhatsApp send failed: {exc}"

    logger.warning("WhatsApp provider '%s' not configured. to=%s", provider, to_number)
    return False, f"Unsupported WhatsApp provider '{provider}'."


def send_booking_confirmed_whatsapp(booking_group, *, source: str = "payment") -> bool:
    """Send booking confirmation to the passenger's WhatsApp number."""
    try:
        bg = (
            type(booking_group)
            .objects.select_related("passenger", "schedule", "schedule__bus", "schedule__route")
            .prefetch_related("bookings")
            .get(pk=booking_group.pk)
        )
    except Exception as exc:
        logger.exception("Could not reload booking group for WhatsApp: %s", exc)
        return False

    if getattr(bg, "whatsapp_status", "NOT_SENT") == "SENT":
        return True

    bg.whatsapp_retry_count = (getattr(bg, "whatsapp_retry_count", 0) or 0) + 1
    bg.whatsapp_last_attempt_at = timezone.now()
    bg.save(update_fields=["whatsapp_retry_count", "whatsapp_last_attempt_at"])

    phone = booking_group_whatsapp_phone(bg)
    if not phone:
        logger.warning("No valid +237 phone for WhatsApp. bg=%s", bg.id)
        bg.whatsapp_status = "FAILED"
        bg.whatsapp_error_message = "No valid Cameroon WhatsApp number on this booking."
        bg.save(update_fields=["whatsapp_status", "whatsapp_error_message"])
        return False

    receipt_code, msg = build_booking_confirmation_message(bg)

    passenger_name = (bg.passenger.name or "").strip()
    date_str, time_str = format_departure_parts(bg.schedule.departure_time)
    bus_type = (bg.schedule.bus.bus_type or "").strip()
    seat_numbers = sorted(bg.bookings.values_list("seat_number", flat=True))
    seat_numbers_str = ", ".join(str(s) for s in seat_numbers) if seat_numbers else "—"

    if not validate_receipt_message(
        message=msg,
        passenger_name=passenger_name,
        date_str=date_str,
        time_str=time_str,
        bus_type=bus_type,
        seat_numbers_str=seat_numbers_str,
    ):
        bg.whatsapp_status = "FAILED"
        bg.whatsapp_error_message = "Receipt message validation failed."
        bg.save(update_fields=["whatsapp_status", "whatsapp_error_message"])
        return False

    ok, error_message = send_whatsapp(phone, msg)
    if not ok:
        bg.whatsapp_status = "FAILED"
        bg.whatsapp_error_message = error_message or "Unknown WhatsApp provider error."
        bg.save(update_fields=["whatsapp_status", "whatsapp_error_message"])
        return False

    bg.whatsapp_receipt_code = receipt_code
    bg.whatsapp_status = "SENT"
    bg.whatsapp_sent_at = timezone.now()
    bg.whatsapp_message_hash = hashlib.sha256(msg.encode("utf-8")).hexdigest()
    bg.whatsapp_error_message = None
    bg.save(
        update_fields=[
            "whatsapp_receipt_code",
            "whatsapp_status",
            "whatsapp_sent_at",
            "whatsapp_message_hash",
            "whatsapp_error_message",
        ]
    )
    return True
