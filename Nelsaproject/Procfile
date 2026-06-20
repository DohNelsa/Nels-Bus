web: python manage.py migrate --noinput && gunicorn Nelsaproject.wsgi:application --bind 0.0.0.0:$PORT --timeout 120 --graceful-timeout 30


