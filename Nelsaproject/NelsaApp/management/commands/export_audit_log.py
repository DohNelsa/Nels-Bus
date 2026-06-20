import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from NelsaApp.models import AdminAuditLog


class Command(BaseCommand):
    help = "Export admin audit log to CSV."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True, help="Output CSV file path.")
        parser.add_argument("--limit", type=int, default=5000)

    def handle(self, *args, **options):
        output = Path(options["output"]).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        rows = AdminAuditLog.objects.select_related("user").order_by("-created_at")[: options["limit"]]

        with output.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["created_at", "user", "action", "target_type", "target_id", "ip_address", "detail_json"])
            for r in rows:
                writer.writerow(
                    [
                        r.created_at.isoformat(),
                        r.user.username if r.user else "",
                        r.action,
                        r.target_type,
                        r.target_id,
                        r.ip_address or "",
                        json.dumps(r.detail or {}, default=str),
                    ]
                )

        self.stdout.write(self.style.SUCCESS(f"Exported {len(rows)} audit records to {output}"))
