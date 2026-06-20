from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from NelsaApp.models import BookingGroup, PaymentWebhookEvent
from NelsaApp.monitoring import send_ops_alert


class Command(BaseCommand):
    help = "Evaluate alert policy thresholds and send operational alerts."

    def handle(self, *args, **options):
        now = timezone.now()
        window_5m = now - timedelta(minutes=5)

        rejected_5m = PaymentWebhookEvent.objects.filter(status="REJECTED", received_at__gte=window_5m).count()
        dead_lettered = PaymentWebhookEvent.objects.filter(dead_lettered=True, processed=False).count()
        sms_failed = BookingGroup.objects.filter(sms_status="FAILED").count()
        pending = BookingGroup.objects.filter(status="Pending").count()

        thresholds = {
            "rejected_5m": int(getattr(settings, "ALERT_WEBHOOK_REJECTED_THRESHOLD_5M", 3)),
            "dead_lettered": int(getattr(settings, "ALERT_WEBHOOK_DEAD_LETTER_THRESHOLD", 1)),
            "sms_failed": int(getattr(settings, "ALERT_SMS_FAILED_THRESHOLD", 20)),
            "pending": int(getattr(settings, "ALERT_PENDING_BOOKINGS_THRESHOLD", 100)),
        }
        metrics = {
            "rejected_5m": rejected_5m,
            "dead_lettered": dead_lettered,
            "sms_failed": sms_failed,
            "pending": pending,
        }

        breaches = [name for name, value in metrics.items() if value >= thresholds[name]]
        if not breaches:
            self.stdout.write(self.style.SUCCESS("No alert thresholds breached."))
            return

        owner = getattr(settings, "ONCALL_OWNER", "ops-team")
        escalation = ", ".join(getattr(settings, "ALERT_ESCALATION_RECIPIENTS", []) or [])
        body = (
            f"Threshold breaches: {', '.join(breaches)}\n"
            f"On-call owner: {owner}\n"
            f"Escalation recipients: {escalation or 'n/a'}\n\n"
            f"Metrics: {metrics}\n"
            f"Thresholds: {thresholds}\n"
            f"Timestamp: {now.isoformat()}\n"
        )
        send_ops_alert("Ops alert threshold breached", body, fail_silently=False)
        self.stdout.write(self.style.WARNING(body))
