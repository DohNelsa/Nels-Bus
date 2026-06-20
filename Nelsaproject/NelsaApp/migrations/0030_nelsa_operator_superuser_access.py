"""Ensure operator accounts nelsa and DohNelsa can confirm bookings."""

from django.db import migrations


def ensure_operator_superusers(apps, schema_editor):
    User = apps.get_model("auth", "User")
    for username in ("nelsa", "DohNelsa"):
        User.objects.filter(username=username).update(
            is_superuser=True,
            is_staff=True,
            is_active=True,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("NelsaApp", "0029_superuser_staff_and_booking_perms"),
    ]

    operations = [
        migrations.RunPython(ensure_operator_superusers, noop_reverse),
    ]
