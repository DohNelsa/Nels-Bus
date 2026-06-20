"""Restore confirm/cancel on Operations Full (stripped by 0020) and ensure staff have ops perms."""

from django.db import migrations

OPS_FULL_CODENAMES = (
    "access_admin_bookings",
    "confirm_bookinggroup",
    "cancel_bookinggroup",
    "manage_refunds_rebooks",
    "view_paymentwebhooks",
    "view_adminauditlog",
    "manage_routes_schedules",
    "manage_sms_ops",
    "manage_staff_users",
)


def restore_ops_full_and_staff(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("auth", "User")

    perms = list(
        Permission.objects.filter(content_type__app_label="NelsaApp", codename__in=OPS_FULL_CODENAMES)
    )
    ops_full, _ = Group.objects.get_or_create(name="Operations Full")
    ops_full.permissions.set(perms)

    ops_core = Group.objects.filter(name="Operations Core").first()
    target = ops_core or ops_full

    for user in User.objects.filter(is_staff=True, is_superuser=False):
        has_confirm = user.groups.filter(
            permissions__codename="confirm_bookinggroup",
            permissions__content_type__app_label="NelsaApp",
        ).exists()
        if not has_confirm and target is not None:
            user.groups.add(target)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("NelsaApp", "0027_staff_ops_group_permissions"),
    ]

    operations = [
        migrations.RunPython(restore_ops_full_and_staff, noop_reverse),
    ]
