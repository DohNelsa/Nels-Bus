"""
Email notifications for booking lifecycle (confirmation, etc.).
"""
import logging
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger(__name__)


def send_booking_confirmed_email(booking_group, *, source: str = "payment") -> bool:
    """
    Send a confirmation email to the passenger when a booking group is confirmed.

    source: 'payment' (user completed payment flow) or 'admin' (staff confirmed manually).
    Returns True if send_mail reported success (1 message sent).
    """
    try:
        bg = (
            type(booking_group)
            .objects.select_related(
                "passenger",
                "payment",
                "schedule",
                "schedule__bus",
                "schedule__route",
            )
            .prefetch_related("bookings")
            .get(pk=booking_group.pk)
        )
    except Exception as exc:
        logger.exception("Could not reload booking group for notification: %s", exc)
        return False

    company = getattr(settings, "COMPANY_NAME", "GARANTI EXPRESS")
    support_email = getattr(settings, "COMPANY_SUPPORT_EMAIL", settings.DEFAULT_FROM_EMAIL)
    support_phone = getattr(settings, "COMPANY_SUPPORT_PHONE", "")
    site_url = getattr(settings, "PUBLIC_SITE_URL", "").rstrip("/")

    passenger = bg.passenger
    to_email = (passenger.email or "").strip()
    if not to_email:
        logger.warning("No passenger email for booking group %s; skipping confirmation email.", bg.id)
        return False

    schedule = bg.schedule
    route = schedule.route
    bus = schedule.bus

    seat_numbers = sorted(bg.bookings.values_list("seat_number", flat=True))
    seats_str = ", ".join(str(s) for s in seat_numbers) if seat_numbers else "—"

    try:
        payment = bg.payment
    except ObjectDoesNotExist:
        payment = None

    amount_paid: Decimal | None = None
    payment_method = "—"
    txn_id = (bg.transaction_id or "").strip() or "—"

    if payment is not None:
        amount_paid = payment.amount
        payment_method = payment.get_payment_method_display() if hasattr(payment, "get_payment_method_display") else str(
            payment.payment_method
        )
        if payment.transaction_id:
            txn_id = payment.transaction_id

    if amount_paid is None:
        amount_paid = bg.total_amount

    confirmed_at = timezone.localtime(timezone.now())
    dep = schedule.departure_time
    arr = schedule.arrival_time

    ref = f"BG-{bg.id:06d}"
    subject = f"{company} — Booking confirmed ({ref})"

    lines = [
        f"Dear {passenger.name},",
        "",
        f"Your booking with {company} is CONFIRMED.",
        "",
        "— Booking details —",
        f"Reference:        {ref}",
        f"Confirmation via: {source}",
        f"Confirmed at:     {confirmed_at.strftime('%Y-%m-%d %H:%M')} ({timezone.get_current_timezone_name()})",
        "",
        f"Route:            {route.start_location} → {route.end_location}",
        f"Bus:              {bus.bus_number} ({bus.bus_type})",
        f"Departure:        {dep.strftime('%Y-%m-%d %H:%M')}",
        f"Arrival:          {arr.strftime('%Y-%m-%d %H:%M')}",
        f"Seat(s):          {seats_str}",
        "",
        "— Payment —",
        f"Amount:           {amount_paid} FCFA",
        f"Payment method:   {payment_method}",
        f"Transaction ID:   {txn_id}",
        "",
        "— Support —",
        f"Support email:    {support_email}",
    ]
    if support_phone:
        lines.append(f"Support phone:    {support_phone}")
    if site_url:
        lines.extend(["", f"Manage bookings: {site_url}/profile/"])

    lines.extend(
        [
            "",
            "Please keep this email for your records.",
            "",
            f"— {company} —",
        ]
    )

    body = "\n".join(lines)

    try:
        sent = send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [to_email],
            fail_silently=False,
        )
        return bool(sent)
    except Exception as exc:
        logger.exception("Failed to send booking confirmation email for BG %s: %s", bg.id, exc)
        return False
