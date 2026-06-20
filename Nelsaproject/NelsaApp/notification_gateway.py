"""
Single entry point for post-confirmation passenger notifications (email + WhatsApp + optional SMS).

Manual Mobile Money flow (default): customer pays and submits transaction ID;
staff confirm the booking in admin — then call `queue_booking_confirmation_notifications`.
"""

from django.conf import settings

from .jobs import enqueue_notification_job, process_one_notification_job


def queue_booking_confirmation_notifications(
    booking_group_id: int,
    *,
    source: str = "staff_confirm",
    skip_whatsapp: bool = False,
) -> None:
    """
    Queue email + WhatsApp (default) and optional SMS for a confirmed booking.
    Set skip_whatsapp=True only when WHATSAPP_ADMIN_HANDOFF is enabled (staff sends via wa.me).
    """
    payload = {"source": source}
    jobs = [enqueue_notification_job(booking_group_id, "BOOKING_CONFIRMED_EMAIL", payload)]

    if not skip_whatsapp and getattr(settings, "WHATSAPP_ENABLED", True):
        jobs.append(enqueue_notification_job(booking_group_id, "BOOKING_CONFIRMED_WHATSAPP", payload))
    elif not skip_whatsapp and getattr(settings, "SMS_ENABLED", False):
        jobs.append(enqueue_notification_job(booking_group_id, "BOOKING_CONFIRMED_SMS", payload))

    if getattr(settings, "BOOKING_CONFIRMATION_SMS_ALSO", False) and getattr(settings, "SMS_ENABLED", False):
        jobs.append(enqueue_notification_job(booking_group_id, "BOOKING_CONFIRMED_SMS", payload))

    if getattr(settings, "NOTIFICATION_FLUSH_JOBS_INLINE", True):
        for job in jobs:
            process_one_notification_job(job)
