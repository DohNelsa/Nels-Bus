"""
Shared booking confirmation receipt text (SMS / WhatsApp).
"""

import secrets

from django.conf import settings
from django.utils import timezone

from .phone_utils import format_phone_display


def build_receipt_code() -> str:
    return f"GAR-{secrets.token_hex(6).upper()}"


def format_departure_parts(dt):
    local_dt = timezone.localtime(dt)
    return local_dt.strftime("%Y-%m-%d"), local_dt.strftime("%H:%M")


def build_booking_confirmation_message(bg, *, receipt_code: str | None = None) -> tuple[str, str]:
    """
    Returns (receipt_code, message) for passenger-facing SMS/WhatsApp receipts.
    """
    code = receipt_code or build_receipt_code()
    passenger_name = (bg.passenger.name or "").strip()
    date_str, time_str = format_departure_parts(bg.schedule.departure_time)
    bus_type = (bg.schedule.bus.bus_type or "").strip()
    seat_numbers = sorted(bg.bookings.values_list("seat_number", flat=True))
    seat_numbers_str = ", ".join(str(s) for s in seat_numbers) if seat_numbers else "—"

    route = bg.schedule.route
    route_str = f"{route.start_location} → {route.end_location}"
    txn = (bg.transaction_id or "").strip()
    txn_part = f"Transaction ID: {txn}\n" if txn else ""
    amount = int(bg.total_amount) if getattr(bg, "total_amount", None) is not None else None
    amount_part = f"Total paid: {amount} FCFA\n" if amount is not None else ""

    msg = (
        f"GARANTI EXPRESS — Booking confirmed\n\n"
        f"Passenger: {passenger_name}\n"
        f"Route: {route_str}\n"
        f"Seats: {seat_numbers_str}\n"
        f"Departure: {date_str} at {time_str}\n"
        f"Bus: {bus_type}\n"
        f"{amount_part}"
        f"{txn_part}"
        f"Receipt code: {code}\n\n"
        f"Support: {format_phone_display(getattr(settings, 'COMPANY_SUPPORT_PHONE', '+237675315422'))}\n\n"
        f"Thank you for choosing GARANTI EXPRESS. Safe travels!"
    )
    return code, msg


def validate_receipt_message(
    *,
    message: str,
    passenger_name: str,
    date_str: str,
    time_str: str,
    bus_type: str,
    seat_numbers_str: str,
) -> bool:
    msg_upper = message.upper()
    return all(
        [
            "GARANTI EXPRESS" in msg_upper,
            passenger_name.strip() and passenger_name.strip() in message,
            date_str in message,
            time_str in message,
            bus_type.strip() and bus_type.strip() in message,
            seat_numbers_str in message,
        ]
    )
