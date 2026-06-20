"""Request middleware for admin permission consistency."""

from .rbac import ensure_superuser_admin_access, refresh_auth_user, effective_is_superuser


class RefreshAuthUserMiddleware:
    """Keep request.user.is_superuser / is_staff in sync with the database every request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request.user, "is_authenticated", False):
            refresh_auth_user(request.user)
            if effective_is_superuser(request.user):
                ensure_superuser_admin_access(request.user)
                refresh_auth_user(request.user)
        return self.get_response(request)
