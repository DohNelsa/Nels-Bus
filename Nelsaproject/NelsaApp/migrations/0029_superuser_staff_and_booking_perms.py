"""Ensure every superuser has is_staff so ops login and confirm/cancel always work."""

from django.db import migrations


def ensure_superusers_are_staff(apps, schema_editor):
    User = apps.get_model("auth", "User")
    User.objects.filter(is_superuser=True, is_staff=False).update(is_staff=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("NelsaApp", "0028_restore_operations_full_permissions"),
    ]

    operations = [
        migrations.RunPython(ensure_superusers_are_staff, noop_reverse),
    ]
