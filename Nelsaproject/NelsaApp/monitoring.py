"""
Operational alerts + lightweight metrics helpers.
"""

import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger("nelsa.ops")


def send_ops_alert(subject: str, body: str, *, fail_silently: bool = True) -> None:
    """
    Send to ALERT_EMAIL_RECIPIENTS (comma-separated env) when configured.
    """
    recipients = getattr(settings, "ALERT_EMAIL_RECIPIENTS", None) or []
    if not recipients:
        logger.warning("ops_alert (no recipients): %s — %s", subject, body[:500])
        return
    try:
        send_mail(
            subject=f"[{getattr(settings, 'COMPANY_NAME', 'Nelsa')}] {subject}",
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@localhost",
            recipient_list=recipients,
            fail_silently=fail_silently,
        )
    except Exception:
        logger.exception("send_ops_alert failed: %s", subject, exc_info=True)
