from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Restore database data from a dumpdata JSON backup (destructive with --flush)."

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True, help="Path to dumpdata JSON file.")
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Flush DB before restore (recommended for full restore).",
        )
        parser.add_argument(
            "--yes-i-know",
            action="store_true",
            help="Required confirmation flag to run restore.",
        )

    def handle(self, *args, **options):
        if not options["yes_i_know"]:
            raise CommandError("Restore blocked. Re-run with --yes-i-know.")
        input_path = Path(options["input"]).expanduser().resolve()
        if not input_path.exists():
            raise CommandError(f"Input backup file not found: {input_path}")

        if options["flush"]:
            call_command("flush", "--no-input")
        call_command("loaddata", str(input_path))
        self.stdout.write(self.style.SUCCESS(f"Restore completed from {input_path}"))
