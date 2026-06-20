from django.db import transaction
from django.utils import timezone

from .models import BookingGroup, NotificationJob
from .notifications import send_booking_confirmed_email
from .sms import send_booking_confirmed_sms
from .whatsapp import send_booking_confirmed_whatsapp


def enqueue_notification_job(booking_group_id: int, job_type: str, payload=None) -> NotificationJob:
    return NotificationJob.objects.create(
        booking_group_id=booking_group_id,
        job_type=job_type,
        status="PENDING",
        payload=payload or {},
    )


def process_one_notification_job(job: NotificationJob) -> bool:
    job.status = "PROCESSING"
    job.save(update_fields=["status", "updated_at"])
    try:
        bg = BookingGroup.objects.get(pk=job.booking_group_id)
        payload = job.payload if isinstance(job.payload, dict) else {}
        source = payload.get("source") or "booking_confirmed"
        if job.job_type == "BOOKING_CONFIRMED_EMAIL":
            ok = bool(send_booking_confirmed_email(bg, source=source))
        elif job.job_type == "BOOKING_CONFIRMED_SMS":
            ok = send_booking_confirmed_sms(bg, source=source)
        elif job.job_type == "BOOKING_CONFIRMED_WHATSAPP":
            ok = send_booking_confirmed_whatsapp(bg, source=source)
        else:
            raise ValueError(f"Unsupported job type: {job.job_type}")

        if ok:
            job.status = "DONE"
            job.error_message = None
        else:
            job.status = "FAILED"
            job.error_message = "Provider send failed."
        job.save(update_fields=["status", "error_message", "updated_at"])
        return ok
    except Exception as exc:
        job.status = "FAILED"
        job.error_message = str(exc)
        job.retry_count = (job.retry_count or 0) + 1
        job.run_after = timezone.now() + timezone.timedelta(minutes=min(30, max(1, job.retry_count)))
        job.save(update_fields=["status", "error_message", "retry_count", "run_after", "updated_at"])
        return False


def process_pending_notification_jobs(limit: int = 50) -> dict:
    now = timezone.now()
    processed = 0
    success = 0
    failed = 0
    with transaction.atomic():
        jobs = list(
            NotificationJob.objects.select_for_update(skip_locked=True)
            .filter(status__in=["PENDING", "FAILED"], run_after__lte=now)
            .order_by("run_after", "id")[:limit]
        )
    for job in jobs:
        processed += 1
        if process_one_notification_job(job):
            success += 1
        else:
            failed += 1
    return {"processed": processed, "success": success, "failed": failed}
