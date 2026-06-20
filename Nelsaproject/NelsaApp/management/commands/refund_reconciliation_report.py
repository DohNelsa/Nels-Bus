import csv
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from NelsaApp.models import BookingGroup


class Command(BaseCommand):
    help = "Generate refund/rebooking reconciliation report as CSV."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True, help="Output CSV file path.")

    def handle(self, *args, **options):
        output = Path(options["output"]).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        qs = BookingGroup.objects.select_related("passenger", "schedule__route", "payment", "rebooking_of").order_by("-created_at")

        with output.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "booking_group_id",
                    "created_at",
                    "passenger",
                    "route",
                    "status",
                    "total_amount",
                    "payment_status",
                    "refund_status",
                    "refund_requested_at",
                    "refund_completed_at",
                    "rebooking_of_id",
                    "is_rebooked_to_other_group",
                ]
            )
            for bg in qs:
                route = f"{bg.schedule.route.start_location} -> {bg.schedule.route.end_location}"
                pay = getattr(bg, "payment", None)
                writer.writerow(
                    [
                        bg.id,
                        bg.created_at.isoformat(),
                        bg.passenger.name,
                        route,
                        bg.status,
                        str(bg.total_amount),
                        pay.status if pay else "",
                        bg.refund_status,
                        bg.refund_requested_at.isoformat() if bg.refund_requested_at else "",
                        bg.refund_completed_at.isoformat() if bg.refund_completed_at else "",
                        bg.rebooking_of_id or "",
                        "yes" if bg.rebookings.exists() else "no",
                    ]
                )

        self.stdout.write(self.style.SUCCESS(f"Refund reconciliation report generated at {output} ({timezone.now().isoformat()})"))
