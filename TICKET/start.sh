#!/usr/bin/env bash
set -e
# Render always uses this path for the repo root - do not rely on $0 or cwd
export PYTHONPATH="/opt/render/project/src"
cd /opt/render/project/src
exec gunicorn TICKET.wsgi:application --log-file -
