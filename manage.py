#!/usr/bin/env python
"""
Run Django from the real app folder: moghamo/Nelsaproject/

The outer moghamo/ folder is a wrapper. Do not use TICKET.settings — that stub
only exposes /admin/ and is not GARANTI EXPRESS.
"""
import os
import sys
from pathlib import Path

NELSAPROJECT = Path(__file__).resolve().parent / "Nelsaproject"

if not (NELSAPROJECT / "manage.py").is_file():
    print("ERROR: Nelsaproject not found at:", NELSAPROJECT, file=sys.stderr)
    sys.exit(1)

os.chdir(NELSAPROJECT)
sys.path.insert(0, str(NELSAPROJECT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Nelsaproject.settings")

from django.core.management import execute_from_command_line  # noqa: E402

if __name__ == "__main__":
    execute_from_command_line(sys.argv)
