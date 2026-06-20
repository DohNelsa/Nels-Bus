from django.db import migrations


PERM_CODENAMES = (
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

FINANCE_PERM_CODENAMES = (
    "access_admin_bookings",
    "view_paymentwebhooks",
    "view_adminauditlog",
    "manage_refunds_rebooks",
)


def create_groups_and_staff(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("auth", "User")

    perms = list(
        Permission.objects.filter(content_type__app_label="NelsaApp", codename__in=PERM_CODENAMES)
    )
    ops, _ = Group.objects.get_or_create(name="Operations Full")
    ops.permissions.set(perms)

    fin_perms = list(
        Permission.objects.filter(
            content_type__app_label="NelsaApp", codename__in=FINANCE_PERM_CODENAMES
        )
    )
    finance, _ = Group.objects.get_or_create(name="Finance")
    finance.permissions.set(fin_perms)

    for u in User.objects.filter(is_staff=True):
        u.groups.add(ops)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("NelsaApp", "0018_refund_rbac_webhook_kind"),
    ]

    operations = [
        migrations.RunPython(create_groups_and_staff, noop_reverse),
    ]
