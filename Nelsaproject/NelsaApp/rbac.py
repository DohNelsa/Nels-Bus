"""
Role-style access using Django auth Group + Permission.

Assign users to groups (e.g. Operations, Finance) in Django admin, or rely on
migration `0019_rbac_default_groups` which grants all custom permissions to staff.
"""

from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from .audit import log_admin_action


OPS_GROUP_NAMES = ("Operations Core", "Operations Full")

# Staff booking actions redirect here when permission is missing (not the public home page).
ADMIN_BOOKING_PERM_REDIRECT = "admin_bookings"

# Permissions that trigger booking self-heal in require_* decorators.
BOOKING_ACTION_CODENAMES = frozenset(
    {
        "confirm_bookinggroup",
        "cancel_bookinggroup",
        "access_admin_bookings",
    }
)


def assign_staff_ops_group(user) -> bool:
    """
    Ensure a staff user belongs to an Operations group with confirm/cancel permissions.
    Called when promoting users to staff so confirm_bookinggroup works immediately.
    """
    if not getattr(user, "is_staff", False):
        return False
    from django.contrib.auth.models import Group

    group = (
        Group.objects.filter(name="Operations Full").first()
        or Group.objects.filter(name="Operations Core").first()
    )
    if group is None:
        return False
    if user.groups.filter(pk=group.pk).exists():
        return False
    user.groups.add(group)
    _clear_user_perm_cache(user)
    return True


def _clear_user_perm_cache(user) -> None:
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        if hasattr(user, attr):
            delattr(user, attr)


def refresh_auth_user(user):
    """Reload is_superuser/is_staff from DB so permission checks match the database."""
    if not getattr(user, "is_authenticated", False):
        return user
    from django.contrib.auth.models import User

    try:
        fresh = User.objects.get(pk=user.pk)
    except User.DoesNotExist:
        return user
    for field in ("is_superuser", "is_staff", "is_active", "username"):
        setattr(user, field, getattr(fresh, field))
    _clear_user_perm_cache(user)
    return user


def effective_is_superuser(user) -> bool:
    """True when the DB row is superuser (handles stale session flags)."""
    if not getattr(user, "is_authenticated", False):
        return False
    refresh_auth_user(user)
    if getattr(user, "is_superuser", False):
        return True
    from django.contrib.auth.models import User

    return User.objects.filter(pk=user.pk, is_superuser=True).exists()


def _grant_booking_action_permissions(user) -> None:
    """Last resort: attach confirm/cancel directly to the user."""
    from django.contrib.auth.models import Permission

    perms = Permission.objects.filter(
        content_type__app_label="NelsaApp",
        codename__in=("confirm_bookinggroup", "cancel_bookinggroup"),
    )
    user.user_permissions.add(*perms)
    _clear_user_perm_cache(user)


def _full_perm(codename: str) -> str:
    return f"NelsaApp.{codename}"


def ensure_staff_booking_permissions(user) -> None:
    """Self-heal: staff without confirm/cancel get Operations group on next admin visit."""
    user = refresh_auth_user(user)
    if not getattr(user, "is_authenticated", False):
        return
    if getattr(user, "is_superuser", False):
        ensure_superuser_admin_access(user)
        return
    if not getattr(user, "is_staff", False):
        return
    if can_confirm_bookings(user) and can_cancel_bookings(user):
        return
    assign_staff_ops_group(user)
    if not can_confirm_bookings(user) or not can_cancel_bookings(user):
        _grant_booking_action_permissions(user)


def ensure_superuser_admin_access(user) -> None:
    """Superusers always need staff flag to reach the ops portal after login."""
    if not getattr(user, "is_authenticated", False):
        return
    if not getattr(user, "is_superuser", False):
        return
    if user.is_staff:
        return
    user.is_staff = True
    user.save(update_fields=["is_staff"])


def can_confirm_bookings(user) -> bool:
    """True for superusers and staff with confirm_bookinggroup."""
    if effective_is_superuser(user):
        return True
    user = refresh_auth_user(user)
    if not user.is_authenticated:
        return False
    return user.has_perm(_full_perm("confirm_bookinggroup"))


def can_cancel_bookings(user) -> bool:
    """True for superusers and staff with cancel_bookinggroup."""
    if effective_is_superuser(user):
        return True
    user = refresh_auth_user(user)
    if not user.is_authenticated:
        return False
    return user.has_perm(_full_perm("cancel_bookinggroup"))


def user_has_perm(user, codename: str) -> bool:
    if not user.is_authenticated:
        return False
    if effective_is_superuser(user):
        return True
    return user.has_perm(_full_perm(codename))


def user_has_any_perm(user, *codenames: str) -> bool:
    if not user.is_authenticated:
        return False
    if effective_is_superuser(user):
        return True
    return any(user.has_perm(_full_perm(c)) for c in codenames)


def require_perm(codename: str):
    """Staff-only: must have NelsaApp.<codename> or superuser."""

    def decorator(view):
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(reverse("Login"))
            refresh_auth_user(request.user)
            _maybe_heal_booking_permissions(request, (codename,))
            if effective_is_superuser(request.user):
                return view(request, *args, **kwargs)
            if not request.user.is_staff:
                messages.error(request, "Staff access required.")
                log_admin_action(
                    request,
                    "access_denied",
                    "Permission",
                    codename,
                    {"reason": "not_staff"},
                )
                return redirect("index")
            if user_has_perm(request.user, codename):
                return view(request, *args, **kwargs)
            messages.error(request, "You do not have permission to perform this action.")
            log_admin_action(
                request,
                "access_denied",
                "Permission",
                codename,
                {"reason": "missing_perm"},
            )
            if codename in BOOKING_ACTION_CODENAMES:
                return redirect(reverse(ADMIN_BOOKING_PERM_REDIRECT))
            return redirect("index")

        return _wrapped

    return decorator


def require_any_perm(*codenames: str):
    def decorator(view):
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(reverse("Login"))
            refresh_auth_user(request.user)
            _maybe_heal_booking_permissions(request, codenames)
            if effective_is_superuser(request.user):
                return view(request, *args, **kwargs)
            if not request.user.is_staff:
                messages.error(request, "Staff access required.")
                log_admin_action(
                    request,
                    "access_denied",
                    "PermissionAny",
                    ",".join(codenames),
                    {"reason": "not_staff"},
                )
                return redirect("index")
            if user_has_any_perm(request.user, *codenames):
                return view(request, *args, **kwargs)
            messages.error(request, "You do not have permission to perform this action.")
            log_admin_action(
                request,
                "access_denied",
                "PermissionAny",
                ",".join(codenames),
                {"reason": "missing_any_perm"},
            )
            if any(c in BOOKING_ACTION_CODENAMES for c in codenames):
                return redirect(reverse(ADMIN_BOOKING_PERM_REDIRECT))
            return redirect("index")

        return _wrapped

    return decorator


def can_access_admin_portal(user) -> bool:
    """Any staff ops area (dashboard, bookings, routes, finance, etc.)."""
    user = refresh_auth_user(user)
    if not user.is_authenticated:
        return False
    if effective_is_superuser(user):
        return True
    return user_has_any_perm(
        user,
        "access_admin_bookings",
        "manage_routes_schedules",
        "view_paymentwebhooks",
        "view_adminauditlog",
        "manage_sms_ops",
        "manage_staff_users",
        "manage_refunds_rebooks",
    )


def _maybe_heal_booking_permissions(request, codenames) -> None:
    """Ensure superuser/staff booking access before permission checks."""
    if any(c in BOOKING_ACTION_CODENAMES for c in codenames):
        ensure_superuser_admin_access(request.user)
        ensure_staff_booking_permissions(request.user)


# Dashboard: any ops role (matches Finance + Operations groups).
require_admin_portal = require_any_perm(
    "access_admin_bookings",
    "manage_routes_schedules",
    "view_paymentwebhooks",
    "view_adminauditlog",
    "manage_sms_ops",
    "manage_staff_users",
    "manage_refunds_rebooks",
)
