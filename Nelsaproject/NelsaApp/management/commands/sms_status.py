"""
Print whether live SMS (Twilio) is configured — no secrets are shown.
"""

from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Show SMS configuration status (Twilio env present / missing; no secrets printed)."

    def handle(self, *args, **options):
        enabled = getattr(settings, "SMS_ENABLED", False)
        provider = getattr(settings, "SMS_PROVIDER", "mock")
        sid = (getattr(settings, "TWILIO_ACCOUNT_SID", "") or "").strip()
        token = (getattr(settings, "TWILIO_AUTH_TOKEN", "") or "").strip()
        from_num = (getattr(settings, "TWILIO_PHONE_NUMBER", "") or "").strip()

        self.stdout.write(f"SMS_ENABLED: {enabled}")
        self.stdout.write(f"SMS_PROVIDER: {provider}")
        self.stdout.write(f"TWILIO_ACCOUNT_SID: {'set (' + sid[:6] + '…)' if sid else 'MISSING'}")
        self.stdout.write(f"TWILIO_AUTH_TOKEN: {'set' if token else 'MISSING'}")
        self.stdout.write(f"TWILIO_PHONE_NUMBER / SMS_FROM_NUMBER: {from_num or 'MISSING'}")

        if not enabled:
            self.stdout.write(self.style.WARNING("SMS is disabled (SMS_ENABLED=False)."))
            return
        if provider == "mock":
            self.stdout.write(self.style.WARNING("SMS_PROVIDER=mock - no real sends; use SMS_PROVIDER=twilio for live."))
            return
        if provider != "twilio":
            self.stdout.write(self.style.WARNING(f"Provider {provider!r} is not fully wired for live sends."))
            return
        if sid and token and from_num:
            self.stdout.write(self.style.SUCCESS("Twilio basics look configured for live send attempts."))
            self.stdout.write("Tip: run  python manage.py sms_test +237XXXXXXXXX  (trial Twilio only sends to verified numbers).")
        else:
            self.stdout.write(self.style.ERROR("Missing Twilio env - set credentials in .env or your host dashboard."))
