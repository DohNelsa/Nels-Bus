"""
Send one WhatsApp message via Twilio (same path as booking confirmations).

Usage:
  py manage.py whatsapp_test +237675315422
  py manage.py whatsapp_test +237675315422 --message "Custom test"
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from NelsaApp.whatsapp import send_whatsapp


class Command(BaseCommand):
    help = "Send one Twilio WhatsApp message to verify credentials (NelsaApp.whatsapp.send_whatsapp)."

    def add_arguments(self, parser):
        parser.add_argument(
            "to",
            help="Passenger phone in E.164, e.g. +237675315422 (must join Twilio sandbox first for testing).",
        )
        parser.add_argument(
            "--message",
            default="",
            help="Optional body; default is a short GARANTI EXPRESS test message.",
        )

    def handle(self, *args, **options):
        to = (options["to"] or "").strip()
        if not to.startswith("+"):
            raise CommandError("Phone must be E.164 (start with +), e.g. +237675315422")

        if not getattr(settings, "WHATSAPP_ENABLED", False):
            raise CommandError("WHATSAPP_ENABLED is False — set WHATSAPP_ENABLED=True in .env")

        provider = getattr(settings, "WHATSAPP_PROVIDER", "mock")
        if provider == "mock":
            raise CommandError(
                "WHATSAPP_PROVIDER is mock — set WHATSAPP_PROVIDER=twilio in .env for a live send."
            )

        company = getattr(settings, "COMPANY_NAME", "GARANTI EXPRESS")
        body = (options["message"] or "").strip() or (
            f"{company}: WhatsApp test OK. Your booking confirmation channel is configured."
        )

        from_addr = getattr(settings, "TWILIO_WHATSAPP_FROM", "") or "(not set)"
        self.stdout.write(f"Provider={provider} To={to} From={from_addr}")

        ok, err = send_whatsapp(to, body)
        if ok:
            self.stdout.write(
                self.style.SUCCESS(
                    "Message accepted by Twilio (check Console → Monitor → Logs → Messaging)."
                )
            )
        else:
            raise CommandError(err or "Send failed — see Django logs and Twilio debugger.")
