"""
Send a single live SMS via the same path as booking confirmations (Twilio).

Usage:
  python manage.py sms_test +237671234567
  python manage.py sms_test +237671234567 --message "Custom test body"
"""

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from NelsaApp.sms import send_sms


class Command(BaseCommand):
    help = "Send one Twilio SMS to verify live credentials (uses NelsaApp.sms.send_sms)."

    def add_arguments(self, parser):
        parser.add_argument(
            "to",
            help="Destination in E.164, e.g. +237671234567 (must match Twilio geo permissions).",
        )
        parser.add_argument(
            "--message",
            default="",
            help="Optional body; default is a short GARANTI EXPRESS configuration test message.",
        )

    def handle(self, *args, **options):
        to = (options["to"] or "").strip()
        if not to.startswith("+"):
            raise CommandError("Phone must be E.164 (start with +), e.g. +237671234567")

        if not getattr(settings, "SMS_ENABLED", False):
            raise CommandError("SMS_ENABLED is False — set SMS_ENABLED=True in the environment.")

        provider = getattr(settings, "SMS_PROVIDER", "mock")
        if provider == "mock":
            raise CommandError("SMS_PROVIDER is mock — set SMS_PROVIDER=twilio for a live send.")

        company = getattr(settings, "COMPANY_NAME", "GARANTI EXPRESS")
        body = (options["message"] or "").strip() or (
            f"{company}: SMS test OK. Your Twilio + Django integration is sending live messages."
        )

        self.stdout.write(f"Provider={provider} To={to} From={(getattr(settings, 'TWILIO_PHONE_NUMBER', '') or '(none)')[:16]}…")

        ok, err = send_sms(to, body)
        if ok:
            self.stdout.write(self.style.SUCCESS("Message accepted by the provider (check Twilio Logs → Messaging)."))
        else:
            raise CommandError(err or "Send failed — see Django logs and Twilio debugger.")
