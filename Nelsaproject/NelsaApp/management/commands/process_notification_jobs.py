from django.core.management.base import BaseCommand

from NelsaApp.jobs import process_pending_notification_jobs


class Command(BaseCommand):
    help = "Process pending SMS/email notification jobs."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        result = process_pending_notification_jobs(limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {result['processed']} jobs (ok={result['success']} failed={result['failed']})"
            )
        )
