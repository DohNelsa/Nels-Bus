"""Ensure superusers and staff can confirm/cancel bookings."""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from NelsaApp.rbac import (
    assign_staff_ops_group,
    ensure_staff_booking_permissions,
    ensure_superuser_admin_access,
    refresh_auth_user,
)


class Command(BaseCommand):
    help = "Grant superusers and staff full booking confirm/cancel access."

    def add_arguments(self, parser):
        parser.add_argument(
            "usernames",
            nargs="*",
            help="Optional usernames to promote to superuser+staff (e.g. Guaranti_admin)",
        )

    def handle(self, *args, **options):
        usernames = options["usernames"]
        if usernames:
            for name in usernames:
                try:
                    user = User.objects.get(username=name)
                except User.DoesNotExist:
                    self.stderr.write(self.style.ERROR(f"User not found: {name}"))
                    continue
                user.is_superuser = True
                user.is_staff = True
                user.is_active = True
                user.save(update_fields=["is_superuser", "is_staff", "is_active"])
                ensure_staff_booking_permissions(user)
                self.stdout.write(self.style.SUCCESS(f"Fixed superuser access: {name}"))

        for user in User.objects.filter(is_superuser=True):
            ensure_superuser_admin_access(user)
            ensure_staff_booking_permissions(user)
            self.stdout.write(f"Superuser OK: {user.username}")

        for user in User.objects.filter(is_staff=True, is_superuser=False):
            refresh_auth_user(user)
            assign_staff_ops_group(user)
            ensure_staff_booking_permissions(user)
            self.stdout.write(f"Staff booking perms OK: {user.username}")

        self.stdout.write(self.style.SUCCESS("Done. Log out and log back in at /Login/"))
