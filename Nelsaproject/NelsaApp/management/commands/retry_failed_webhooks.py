from django.core.management.base import BaseCommand
from django.utils import timezone

from NelsaApp.models import PaymentWebhookEvent
from NelsaApp.views import _mark_webhook_failed, _process_payment_event


class Command(BaseCommand):
    help = "Retry failed/rejected payment webhook events that are not dead-lettered."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        qs = PaymentWebhookEvent.objects.filter(
            processed=False, dead_lettered=False, status__in=["FAILED", "REJECTED"]
        ).order_by("received_at")[: options["limit"]]
        total = 0
        ok = 0
        failed = 0
        for ev in qs:
            total += 1
            try:
                _process_payment_event(ev.payload or {}, ev)
                ev.processed = True
                ev.status = "PROCESSED"
                ev.error_message = None
                ev.last_retry_at = timezone.now()
                ev.processed_at = timezone.now()
                ev.save(
                    update_fields=[
                        "processed",
                        "status",
                        "error_message",
                        "last_retry_at",
                        "processed_at",
                        "booking_group",
                    ]
                )
                ok += 1
            except Exception as exc:
                _mark_webhook_failed(ev, exc, status="REJECTED")
                failed += 1
        self.stdout.write(self.style.SUCCESS(f"Retried {total} webhook(s): ok={ok}, failed={failed}"))
