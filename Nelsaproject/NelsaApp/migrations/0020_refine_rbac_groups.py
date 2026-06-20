from django.db import migrations


def _set_group_perms(Group, Permission, name, codenames):
    group, _ = Group.objects.get_or_create(name=name)
    perms = list(Permission.objects.filter(content_type__app_label="NelsaApp", codename__in=codenames))
    group.permissions.set(perms)
    return group


def forwards(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("auth", "User")

    ops_core = _set_group_perms(
        Group,
        Permission,
        "Operations Core",
        (
            "access_admin_bookings",
            "confirm_bookinggroup",
            "cancel_bookinggroup",
            "manage_sms_ops",
            "manage_refunds_rebooks",
            "view_adminauditlog",
        ),
    )
    _set_group_perms(
        Group,
        Permission,
        "Finance Core",
        (
            "access_admin_bookings",
            "view_paymentwebhooks",
            "manage_refunds_rebooks",
            "view_adminauditlog",
        ),
    )
    _set_group_perms(
        Group,
        Permission,
        "Routes & Fleet",
        (
            "access_admin_bookings",
            "manage_routes_schedules",
            "view_adminauditlog",
        ),
    )
    _set_group_perms(
        Group,
        Permission,
        "Support Core",
        (
            "access_admin_bookings",
            "manage_sms_ops",
            "view_adminauditlog",
        ),
    )
    _set_group_perms(
        Group,
        Permission,
        "User Admin",
        (
            "manage_staff_users",
            "view_adminauditlog",
        ),
    )

    # Tighten legacy broad assignment from previous migration.
    try:
        ops_full = Group.objects.get(name="Operations Full")
    except Group.DoesNotExist:
        ops_full = None
    if ops_full:
        for user in User.objects.filter(is_staff=True, is_superuser=False, groups=ops_full):
            user.groups.add(ops_core)
            user.groups.remove(ops_full)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("NelsaApp", "0019_rbac_default_groups"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
