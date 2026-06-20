"""
SEO: canonical URL, default Open Graph image, public site base for JSON-LD.
"""
import json

from django.conf import settings
from django.templatetags.static import static

from .phone_utils import format_phone_display, normalize_cameroon_phone, phone_wa_me_digits


def _company_phone():
    raw = getattr(settings, "COMPANY_SUPPORT_PHONE", "+237675315422")
    return normalize_cameroon_phone(raw) or "+237675315422"


def site_seo(request):
    path = request.path_info or "/"
    try:
        canonical_url = request.build_absolute_uri(path)
    except Exception:
        canonical_url = f"{getattr(settings, 'PUBLIC_SITE_URL', 'http://127.0.0.1:8000').rstrip('/')}{path}"
    public = getattr(settings, "PUBLIC_SITE_URL", "http://127.0.0.1:8000").rstrip("/")
    try:
        og_path = static("garanti-home-bus.png")
        og_image = request.build_absolute_uri(og_path)
    except Exception:
        og_image = f"{public}{static('garanti-home-bus.png')}"
    name = getattr(settings, "COMPANY_NAME", "GARANTI EXPRESS")
    phone = _company_phone()
    phone_display = format_phone_display(phone)
    phone_wa = phone_wa_me_digits(phone)
    org_ld = {
        "@context": "https://schema.org",
        "@type": "TravelAgency",
        "name": name,
        "url": public,
        "telephone": phone,
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Douala",
            "addressCountry": "CM",
        },
        "description": "Intercity bus booking and travel across Cameroon.",
    }
    return {
        "canonical_url": canonical_url,
        "og_image": og_image,
        "public_site_url": public,
        "company_name": name,
        "company_phone": phone,
        "company_phone_display": phone_display,
        "company_phone_wa": phone_wa,
        "company_phone_tel": f"tel:{phone}",
        "seo_default_description": (
            "Book intercity bus tickets in Cameroon. GARANTI EXPRESS — online booking, "
            "routes, secure payment, and 24/7 support."
        ),
        "organization_json_ld": json.dumps(org_ld, ensure_ascii=True),
    }


def admin_booking_permissions(request):
    """Global confirm/cancel flags for admin templates (fresh DB user, self-healed staff)."""
    from django.contrib.auth.models import User

    from .rbac import (
        can_cancel_bookings,
        can_confirm_bookings,
        effective_is_superuser,
        ensure_staff_booking_permissions,
        ensure_superuser_admin_access,
        refresh_auth_user,
    )

    user = refresh_auth_user(request.user)
    if not user.is_authenticated:
        return {
            "user_can_confirm": False,
            "user_can_cancel": False,
            "is_booking_admin": False,
            "is_effective_superuser": False,
            "show_booking_confirm_actions": False,
            "show_booking_cancel_actions": False,
            "signed_in_username": "",
        }

    db_user = User.objects.filter(pk=user.pk).only("is_superuser", "is_staff", "username").first()
    if effective_is_superuser(user) or user.is_staff:
        ensure_superuser_admin_access(user)
        ensure_staff_booking_permissions(user)
        refresh_auth_user(user)

    is_super = bool(db_user and db_user.is_superuser) or effective_is_superuser(user)
    if is_super:
        ensure_superuser_admin_access(user)
        refresh_auth_user(user)

    can_confirm = is_super or can_confirm_bookings(user)
    can_cancel = is_super or can_cancel_bookings(user)

    return {
        "user_can_confirm": can_confirm,
        "user_can_cancel": can_cancel,
        "is_booking_admin": is_super or (db_user and db_user.is_staff) or user.is_staff,
        "is_effective_superuser": is_super,
        "show_booking_confirm_actions": can_confirm,
        "show_booking_cancel_actions": can_cancel,
        "signed_in_username": getattr(db_user, "username", user.username) if db_user else user.username,
    }
