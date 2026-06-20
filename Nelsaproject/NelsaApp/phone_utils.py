"""
Cameroon phone numbers: store as E.164 with +237.

Users may type national format (e.g. 699123456) or international; we normalize to +237…
"""

from __future__ import annotations

import re


def normalize_cameroon_phone(phone_raw: str | None) -> str | None:
    """
    Normalize and validate a Cameroon MSISDN.

    Accepts:
    - +237699123456, +237 699 123 456
    - 237699123456, 00237699123456
    - 699123456 (9 digits, mobile typically starts with 6)
    - 0699123456 (leading 0 + 9 digit national)

    Returns None if invalid or empty.
    """
    if phone_raw is None:
        return None

    phone = str(phone_raw).strip()
    if not phone:
        return None

    phone = re.sub(r"[\s\-\(\)]", "", phone)

    if phone.startswith("00"):
        phone = "+" + phone[2:]

    # Digits-only copy for inference when user omitted +237
    digits = re.sub(r"\D", "", phone)

    if not phone.startswith("+"):
        # 237 + 9 or 8 digit national (12 or 11 digits total)
        if digits.startswith("237") and len(digits) >= 11:
            phone = "+" + digits
        # National mobile: optional leading 0
        elif digits.startswith("0") and len(digits) == 10:
            digits = digits[1:]
            if len(digits) == 9 and digits.startswith("6"):
                phone = "+237" + digits
            else:
                return None
        # 9-digit national (mobile)
        elif len(digits) == 9 and digits.startswith("6"):
            phone = "+237" + digits
        # 8-digit national (allowed legacy / short)
        elif len(digits) == 8 and digits.startswith("6"):
            phone = "+237" + digits
        else:
            return None

    if not phone.startswith("+237"):
        return None

    inner = re.sub(r"\D", "", phone)
    if not inner.startswith("237"):
        return None

    national = inner[3:]
    if len(national) not in (8, 9):
        return None

    return "+237" + national


def format_phone_display(phone_raw: str | None) -> str:
    """Format E.164 Cameroon number for display, e.g. +237 675 315 422."""
    normalized = normalize_cameroon_phone(phone_raw)
    if not normalized or not normalized.startswith("+237"):
        return (phone_raw or "").strip()
    national = normalized[4:]
    if len(national) == 9:
        return f"+237 {national[:3]} {national[3:6]} {national[6:]}"
    if len(national) == 8:
        return f"+237 {national[:2]} {national[2:5]} {national[5:]}"
    return normalized


def phone_wa_me_digits(phone_raw: str | None) -> str:
    """Digits only for wa.me links (no +), e.g. 237675315422."""
    normalized = normalize_cameroon_phone(phone_raw)
    if normalized:
        return re.sub(r"\D", "", normalized)
    return re.sub(r"\D", "", phone_raw or "")


def national_cameroon_digits(phone_raw: str | None) -> str:
    """National number without country code, e.g. 675315422."""
    normalized = normalize_cameroon_phone(phone_raw)
    if normalized and normalized.startswith("+237"):
        return normalized[4:]
    digits = re.sub(r"\D", "", phone_raw or "")
    if digits.startswith("237") and len(digits) > 3:
        return digits[3:]
    return digits.lstrip("0")
