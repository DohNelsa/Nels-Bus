"""Twilio credential helpers — catch bad .env values before API calls."""

from __future__ import annotations

_PLACEHOLDER_FRAGMENTS = (
    "your_account_sid",
    "your_auth_token",
    "changeme",
    "replace_me",
    "xxx",
    "example",
)


def clean_env_secret(value: str) -> str:
    """Strip whitespace and optional surrounding quotes from .env values."""
    cleaned = (value or "").strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
        cleaned = cleaned[1:-1].strip()
    return cleaned


def looks_like_placeholder(value: str) -> bool:
    lowered = (value or "").strip().lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in _PLACEHOLDER_FRAGMENTS)


def is_valid_account_sid(account_sid: str) -> bool:
    """Live/test Account SID — always starts with AC and is 34 characters."""
    sid = (account_sid or "").strip()
    return sid.startswith("AC") and len(sid) == 34


def is_valid_auth_token(auth_token: str) -> bool:
    token = (auth_token or "").strip()
    return len(token) >= 16 and not looks_like_placeholder(token)


def validate_twilio_whatsapp_credentials(
    *,
    account_sid: str,
    auth_token: str,
    whatsapp_from: str,
) -> str | None:
    """
    Return None if credentials look usable, else a short admin-facing error message.
    """
    sid = (account_sid or "").strip()
    token = (auth_token or "").strip()
    sender = (whatsapp_from or "").strip()

    if not sid or not token or not sender:
        return (
            "Twilio WhatsApp is not configured. Set TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, and TWILIO_WHATSAPP_FROM in Nelsaproject/.env "
            "(see .env.example), then restart the server."
        )

    if looks_like_placeholder(sid) or looks_like_placeholder(token):
        return (
            "Twilio credentials in .env are still placeholders (e.g. your_account_sid). "
            "Copy the real Account SID and Auth Token from https://console.twilio.com "
            "(Account - API keys & tokens), then restart the server."
        )

    if sid.startswith("SK"):
        return (
            "TWILIO_ACCOUNT_SID must be your Account SID (starts with AC), not an API Key SID (SK…). "
            "Find Account SID on https://console.twilio.com under Account Info."
        )

    if not is_valid_account_sid(sid):
        return (
            "TWILIO_ACCOUNT_SID is invalid. It must start with AC and be 34 characters. "
            "Copy it from Twilio Console → Account Info (not the Auth Token)."
        )

    if not is_valid_auth_token(token):
        return (
            "TWILIO_AUTH_TOKEN is missing or looks invalid. "
            "Copy the primary Auth Token from Twilio Console (Account - API keys & tokens). "
            "If you regenerated it, update .env and restart the server."
        )

    if "whatsapp:" not in sender.lower():
        return (
            "TWILIO_WHATSAPP_FROM must include the whatsapp: prefix, "
            "e.g. whatsapp:+14155238886 (from Twilio Console - Messaging - WhatsApp sandbox)."
        )

    return None


def should_use_whatsapp_handoff() -> tuple[bool, str | None]:
    """
    True when staff should send via wa.me (manual) instead of Twilio API.
    Auto-falls back when Twilio credentials are missing/placeholders.
    """
    from django.conf import settings

    if not getattr(settings, "WHATSAPP_ENABLED", True):
        return False, None
    if getattr(settings, "WHATSAPP_ADMIN_HANDOFF", True):
        return True, None
    if getattr(settings, "WHATSAPP_PROVIDER", "mock") != "twilio":
        return False, None
    config_error = getattr(settings, "TWILIO_WHATSAPP_CONFIG_ERROR", None)
    if config_error:
        return True, config_error
    return False, None
