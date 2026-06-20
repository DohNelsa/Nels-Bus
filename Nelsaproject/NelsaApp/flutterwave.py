"""
Flutterwave payment integration (test/live) with local simulate fallback.
"""

from __future__ import annotations

import logging
import re
import secrets
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

FLUTTERWAVE_API_BASE = "https://api.flutterwave.com/v3"


def payment_provider() -> str:
    return (getattr(settings, "PAYMENT_PROVIDER", "flutterwave") or "flutterwave").strip().lower()


def is_flutterwave_enabled() -> bool:
    return payment_provider() == "flutterwave"


def is_simulate_mode() -> bool:
    """Simulate when no secret key, unless explicitly disabled."""
    if (getattr(settings, "FLUTTERWAVE_SECRET_KEY", "") or "").strip():
        return False
    return getattr(settings, "FLUTTERWAVE_SIMULATE", True)


def _prefix() -> str:
    return getattr(settings, "PAYMENT_REFERENCE_PREFIX", "GAR")


def build_tx_ref(booking_group_id: int) -> str:
    return f"{_prefix()}{booking_group_id}-{secrets.token_hex(4).upper()}"


def parse_booking_group_id_from_tx_ref(tx_ref: str) -> int | None:
    if not tx_ref:
        return None
    ref = str(tx_ref).strip()
    prefix = re.escape(_prefix())
    match = re.match(rf"^{prefix}(\d+)", ref, re.IGNORECASE)
    if not match:
        match = re.match(rf"^{prefix}-(\d+)", ref, re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _payment_options_for_method(payment_method: str) -> str:
    method = (payment_method or "CARD").upper()
    if method == "MOMO":
        return "mobilemoneycmr,ussd"
    if method == "ORANGE":
        return "mobilemoneycmr,ussd"
    return "card,mobilemoneycmr"


def _headers() -> dict[str, str]:
    secret = (getattr(settings, "FLUTTERWAVE_SECRET_KEY", "") or "").strip()
    return {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }


def callback_url(booking_group_id: int, checkout_token: str = "") -> str:
    base = getattr(settings, "PUBLIC_SITE_URL", "http://127.0.0.1:8000").rstrip("/")
    path = reverse("flutterwave_callback", kwargs={"booking_group_id": booking_group_id})
    url = f"{base}{path}"
    if checkout_token:
        url = f"{url}?{urlencode({'checkout': checkout_token})}"
    return url


def initialize_payment(
    *,
    booking_group,
    payment_method: str,
    checkout_token: str = "",
) -> tuple[bool, str | None, dict[str, Any]]:
    """
    Start a Flutterwave hosted checkout. Returns (ok, payment_link, meta).
    In simulate mode returns (True, None, meta) — caller shows local simulate UI.
    """
    passenger = booking_group.passenger
    tx_ref = build_tx_ref(booking_group.id)
    amount = float(booking_group.total_amount)
    currency = getattr(settings, "FLUTTERWAVE_CURRENCY", "XAF")

    meta = {
        "tx_ref": tx_ref,
        "amount": amount,
        "currency": currency,
        "payment_method": payment_method,
        "simulate": is_simulate_mode(),
    }

    if is_simulate_mode():
        logger.info("Flutterwave simulate mode for bg=%s tx_ref=%s", booking_group.id, tx_ref)
        return True, None, meta

    secret = (getattr(settings, "FLUTTERWAVE_SECRET_KEY", "") or "").strip()
    if not secret:
        return False, None, {"error": "FLUTTERWAVE_SECRET_KEY is not configured."}

    payload = {
        "tx_ref": tx_ref,
        "amount": amount,
        "currency": currency,
        "redirect_url": callback_url(booking_group.id, checkout_token),
        "payment_options": _payment_options_for_method(payment_method),
        "customer": {
            "email": passenger.email or f"booking{booking_group.id}@garanti.local",
            "name": (passenger.name or "Passenger").strip()[:120],
            "phonenumber": (passenger.phone or "").strip() or None,
        },
        "customizations": {
            "title": getattr(settings, "COMPANY_NAME", "GARANTI EXPRESS"),
            "description": f"Bus booking #{booking_group.id}",
            "logo": "",
        },
        "meta": {
            "booking_group_id": booking_group.id,
            "payment_method": payment_method,
        },
    }
    payload["customer"] = {k: v for k, v in payload["customer"].items() if v}

    try:
        resp = requests.post(
            f"{FLUTTERWAVE_API_BASE}/payments",
            json=payload,
            headers=_headers(),
            timeout=30,
        )
        data = resp.json() if resp.content else {}
    except requests.RequestException as exc:
        logger.exception("Flutterwave initialize failed: %s", exc)
        return False, None, {"error": str(exc)}

    if resp.status_code >= 400 or data.get("status") != "success":
        err = data.get("message") or data.get("error") or resp.text
        logger.warning("Flutterwave init rejected: %s", err)
        return False, None, {"error": str(err), "response": data}

    link = (data.get("data") or {}).get("link")
    if not link:
        return False, None, {"error": "Flutterwave did not return a payment link.", "response": data}

    meta["flw_init"] = data.get("data")
    return True, link, meta


def verify_by_tx_ref(tx_ref: str) -> tuple[bool, dict[str, Any]]:
    """Verify transaction status using tx_ref."""
    if is_simulate_mode():
        bg_id = parse_booking_group_id_from_tx_ref(tx_ref)
        return True, {
            "status": "successful",
            "tx_ref": tx_ref,
            "id": f"SIM-{tx_ref}",
            "amount": None,
            "currency": getattr(settings, "FLUTTERWAVE_CURRENCY", "XAF"),
            "booking_group_id": bg_id,
            "simulate": True,
        }

    secret = (getattr(settings, "FLUTTERWAVE_SECRET_KEY", "") or "").strip()
    if not secret:
        return False, {"error": "FLUTTERWAVE_SECRET_KEY is not configured."}

    try:
        resp = requests.get(
            f"{FLUTTERWAVE_API_BASE}/transactions/verify_by_reference",
            params={"tx_ref": tx_ref},
            headers=_headers(),
            timeout=30,
        )
        data = resp.json() if resp.content else {}
    except requests.RequestException as exc:
        logger.exception("Flutterwave verify failed: %s", exc)
        return False, {"error": str(exc)}

    if resp.status_code >= 400 or data.get("status") != "success":
        return False, {"error": data.get("message") or "Verification failed", "response": data}

    tx = data.get("data") or {}
    status = str(tx.get("status") or "").lower()
    if status != "successful":
        return False, {"error": f"Payment status: {status or 'unknown'}", "data": tx}

    return True, tx


def normalize_flutterwave_webhook(payload: dict) -> dict | None:
    """
    Map Flutterwave charge.completed webhook to internal payment webhook payload.
    """
    event = str(payload.get("event") or "").strip().lower()
    if event not in ("charge.completed", "charge.complete"):
        return None

    data = payload.get("data") or {}
    tx_ref = str(data.get("tx_ref") or "").strip()
    bg_id = parse_booking_group_id_from_tx_ref(tx_ref)
    if not bg_id:
        meta = data.get("meta") or {}
        try:
            bg_id = int(meta.get("booking_group_id"))
        except (TypeError, ValueError):
            return None

    payment_method = str((data.get("meta") or {}).get("payment_method") or "CARD").upper()
    flw_id = data.get("id")
    transaction_id = str(flw_id or data.get("flw_ref") or tx_ref)

    status_raw = str(data.get("status") or "").lower()
    provider_status = "SUCCESS" if status_raw == "successful" else status_raw.upper()

    return {
        "event_id": f"FLW-{flw_id or tx_ref}",
        "provider": "FLUTTERWAVE",
        "booking_group_id": bg_id,
        "payment_method": payment_method,
        "transaction_id": transaction_id,
        "status": provider_status,
        "amount": str(data.get("amount") or ""),
    }


def build_internal_webhook_payload(
    *,
    booking_group_id: int,
    payment_method: str,
    transaction_id: str,
    amount: Decimal | float,
    tx_ref: str | None = None,
) -> dict:
    event_id = f"SIM-{tx_ref or transaction_id}-{secrets.token_hex(4)}"
    return {
        "event_id": event_id,
        "provider": "FLUTTERWAVE",
        "booking_group_id": booking_group_id,
        "payment_method": payment_method,
        "transaction_id": transaction_id,
        "status": "SUCCESS",
        "amount": str(amount),
        "tx_ref": tx_ref,
        "simulated_at": timezone.now().isoformat(),
    }
