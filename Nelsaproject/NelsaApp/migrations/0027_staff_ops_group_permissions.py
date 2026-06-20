"""Ensure all staff users can confirm/cancel bookings (Operations Full group)."""

from django.db import migrations


def assign_ops_group_to_staff(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Group = apps.get_model("auth", "Group")

    group = Group.objects.filter(name="Operations Full").first()
    if group is None:
        group = Group.objects.filter(name="Operations Core").first()
    if group is None:
        return

    for user in User.objects.filter(is_staff=True):
        if not user.groups.filter(pk=group.pk).exists():
            user.groups.add(group)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("NelsaApp", "0026_bookinggroup_customer_phone"),
    ]

    operations = [
        migrations.RunPython(assign_ops_group_to_staff, noop_reverse),
    ]
