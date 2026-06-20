# SMS functionality disabled
# from django.core.management.base import BaseCommand
# from django.conf import settings
# from NelsaApp.sms_service import SMSService, send_booking_confirmation_sms, send_booking_cancellation_sms
# from NelsaApp.models import BookingGroup, Passenger, Schedule, Route, Bus
# from django.utils import timezone
# from datetime import timedelta

# class Command(BaseCommand):
#     help = 'Test SMS sending functionality - DISABLED'

#     def add_arguments(self, parser):
#         pass

#     def handle(self, *args, **options):
#         self.stdout.write(self.style.WARNING('SMS functionality has been disabled.'))
#         self.stdout.write('To re-enable SMS, uncomment this file and set SMS_ENABLED = True in settings.py') 