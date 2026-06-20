#!/usr/bin/env python3
"""
Bootstrap so Gunicorn finds the TICKET package on Render.
Run: python run_gunicorn.py
"""
import os
import sys

# Add repo root to path so "TICKET" can be imported
RENDER_ROOT = "/opt/render/project/src"
if os.path.isdir(RENDER_ROOT):
    sys.path.insert(0, RENDER_ROOT)
else:
    # Local: use directory containing this script
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.chdir(sys.path[0])

# Now run gunicorn with TICKET.wsgi
from gunicorn.app.wsgiapp import run
if __name__ == "__main__":
    port = os.environ.get("PORT", "10000")
    sys.argv = [
        "gunicorn", "TICKET.wsgi:application",
        "--bind", f"0.0.0.0:{port}",
        "--log-file", "-",
    ]
    run()
