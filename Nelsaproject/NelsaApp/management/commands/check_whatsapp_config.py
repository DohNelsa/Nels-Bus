"""Verify Twilio WhatsApp configuration before going live."""

from django.conf import settings
from django.core.management.base import BaseCommand

from NelsaApp.twilio_config import validate_twilio_whatsapp_credentials


class Command(BaseCommand):
    help = "Check Twilio WhatsApp credentials in .env (fixes HTTP 401 invalid username errors)."

    def handle(self, *args, **options):
        sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
        token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
        sender = getattr(settings, "TWILIO_WHATSAPP_FROM", "")
        provider = getattr(settings, "WHATSAPP_PROVIDER", "")
        enabled = getattr(settings, "WHATSAPP_ENABLED", False)

        self.stdout.write(f"WHATSAPP_ENABLED={enabled}")
        self.stdout.write(f"WHATSAPP_PROVIDER={provider}")
        if sid:
            self.stdout.write(f"TWILIO_ACCOUNT_SID=set (starts with {sid[:2]}, length {len(sid)})")
        else:
            self.stdout.write("TWILIO_ACCOUNT_SID=missing")
        self.stdout.write(f"TWILIO_AUTH_TOKEN={'set' if token else 'missing'}")
        self.stdout.write(f"TWILIO_WHATSAPP_FROM={sender or 'missing'}")

        error = validate_twilio_whatsapp_credentials(
            account_sid=sid,
            auth_token=token,
            whatsapp_from=sender,
        )
        if error:
            self.stdout.write(self.style.ERROR(f"Config problem: {error}"))
            self.stdout.write(
                "\nSteps:\n"
                "1. Open https://console.twilio.com\n"
                "2. Copy Account SID (starts with AC) and Auth Token\n"
                "3. Paste into Nelsaproject/.env — no quotes needed\n"
                "4. Set TWILIO_WHATSAPP_FROM=whatsapp:+… from Twilio WhatsApp sandbox\n"
                "5. Set WHATSAPP_PROVIDER=twilio and restart the Django server\n"
            )
            return

        self.stdout.write(self.style.SUCCESS("Twilio WhatsApp credentials look valid."))
        if provider != "twilio":
            self.stdout.write(
                self.style.WARNING(
                    f"WHATSAPP_PROVIDER is '{provider}'. Set WHATSAPP_PROVIDER=twilio in .env to send live messages."
                )
            )
