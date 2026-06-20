import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create an application backup bundle (data fixture + optional sqlite file copy)."

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default="backups", help="Directory for backup artifacts.")

    def handle(self, *args, **options):
        output_root = Path(options["output_dir"]).expanduser().resolve()
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        target = output_root / f"backup-{ts}"
        target.mkdir(parents=True, exist_ok=True)

        fixture_path = target / "dumpdata.json"
        with fixture_path.open("w", encoding="utf-8") as out:
            call_command("dumpdata", "--natural-foreign", "--natural-primary", stdout=out)

        db = settings.DATABASES["default"]
        sqlite_copy = None
        if db.get("ENGINE") == "django.db.backends.sqlite3":
            db_file = Path(db.get("NAME"))
            if db_file.exists():
                sqlite_copy = target / db_file.name
                shutil.copy2(db_file, sqlite_copy)

        self.stdout.write(self.style.SUCCESS(f"Backup created in: {target}"))
        self.stdout.write(f"- fixture: {fixture_path}")
        if sqlite_copy:
            self.stdout.write(f"- sqlite copy: {sqlite_copy}")
