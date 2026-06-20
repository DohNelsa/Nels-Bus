"""
Persist staff action audit entries and mirror to the nelsa.audit logger.
"""

import json
import logging

logger = logging.getLogger("nelsa.audit")


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def log_admin_action(request, action: str, target_type: str, target_id, detail=None):
    """
    Record an admin action. Safe to call from views: DB failures are logged, not raised.
    """
    from .models import AdminAuditLog

    user = getattr(request, "user", None)
    uid = user.pk if getattr(user, "is_authenticated", False) else None
    payload = detail if isinstance(detail, dict) else {}
    ip = _client_ip(request)
    try:
        AdminAuditLog.objects.create(
            user_id=uid,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else "",
            detail=payload,
            ip_address=ip,
        )
    except Exception:
        logger.exception("Failed to persist admin audit action=%s", action)
    logger.info(
        "admin_audit action=%s target=%s:%s user=%s ip=%s detail=%s",
        action,
        target_type,
        target_id,
        uid,
        ip,
        json.dumps(payload, default=str),
    )
