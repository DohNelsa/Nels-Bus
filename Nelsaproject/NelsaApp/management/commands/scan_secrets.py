import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
]

EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "env", "backups"}


class Command(BaseCommand):
    help = "Scan repository text files for likely secrets (best-effort guardrail)."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=".", help="Root path to scan.")

    def handle(self, *args, **options):
        root = Path(options["path"]).expanduser().resolve()
        findings = []
        for p in root.rglob("*"):
            if p.is_dir():
                continue
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".pyc", ".sqlite3"}:
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for pat in PATTERNS:
                if pat.search(txt):
                    findings.append(f"{p}: {pat.pattern}")
                    break

        if findings:
            for f in findings:
                self.stdout.write(self.style.ERROR(f))
            raise CommandError(f"Secret scan failed with {len(findings)} finding(s).")
        self.stdout.write(self.style.SUCCESS("Secret scan passed with no findings."))
