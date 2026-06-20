#!/usr/bin/env bash
# Force PYTHONPATH and cwd so "TICKET" is always found on Render
export PYTHONPATH="/opt/render/project/src"
cd /opt/render/project/src
exec gunicorn TICKET.wsgi:application --bind 0.0.0.0:${PORT:-10000} --log-file -
