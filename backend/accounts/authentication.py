from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import exceptions
from rest_framework.permissions import SAFE_METHODS
from rest_framework_simplejwt.authentication import JWTAuthentication


class _CSRFCheck(CsrfViewMiddleware):
    def _reject(self, request, reason):
        return reason


def enforce_csrf(request):
    """Cookie-based auth needs CSRF protection on every state-changing request."""
    request = getattr(request, "_request", request)  # plain Django request: no DRF body parsing
    check = _CSRFCheck(lambda r: None)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise exceptions.PermissionDenied(f"CSRF check failed: {reason}")


class CookieJWTAuthentication(JWTAuthentication):
    """Reads the access JWT from an httpOnly cookie instead of the Authorization header."""

    def authenticate(self, request):
        raw = request.COOKIES.get(settings.ACCESS_COOKIE)
        if not raw:
            return None
        token = self.get_validated_token(raw)
        user = self.get_user(token)
        if request.method not in SAFE_METHODS:
            enforce_csrf(request)
        return user, token
