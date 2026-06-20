from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone


def client_ip(request):
    xff = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return (request.META.get("REMOTE_ADDR") or "").strip()


def ip_allowlist(setting_name: str):
    """
    Restrict endpoint by source IP. If allowlist is empty, request is allowed.
    """

    def decorator(view):
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            allow = getattr(settings, setting_name, []) or []
            if not allow:
                return view(request, *args, **kwargs)
            ip = client_ip(request)
            if ip in allow:
                return view(request, *args, **kwargs)
            return JsonResponse({"success": False, "message": "IP not allowed"}, status=403)

        return _wrapped

    return decorator


def rate_limit(*, key_prefix: str, limit, window_seconds: int):
    """
    Fixed-window throttle backed by Django cache.
    """

    def decorator(view):
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            ip = client_ip(request) or "unknown"
            now = int(timezone.now().timestamp())
            window = now // max(1, window_seconds)
            key = f"rl:{key_prefix}:{ip}:{window}"

            added = cache.add(key, 1, timeout=window_seconds)
            if added:
                count = 1
            else:
                try:
                    count = cache.incr(key)
                except ValueError:
                    cache.set(key, 1, timeout=window_seconds)
                    count = 1

            max_limit = limit(request) if callable(limit) else int(limit)
            if count > max_limit:
                return JsonResponse(
                    {"success": False, "message": "Too many requests. Please retry later."},
                    status=429,
                )
            return view(request, *args, **kwargs)

        return _wrapped

    return decorator
