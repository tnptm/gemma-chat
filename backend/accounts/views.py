from django.conf import settings
from django.middleware.csrf import get_token
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .authentication import enforce_csrf

ACCESS, REFRESH = settings.ACCESS_COOKIE, settings.REFRESH_COOKIE
ACCESS_PATH, REFRESH_PATH = "/api/", "/api/auth/"  # refresh cookie is only sent to auth endpoints


def set_auth_cookies(resp, access=None, refresh=None):
    jwt = settings.SIMPLE_JWT
    common = dict(httponly=True, secure=settings.COOKIE_SECURE, samesite="Strict")
    if access:
        resp.set_cookie(ACCESS, access, max_age=int(jwt["ACCESS_TOKEN_LIFETIME"].total_seconds()),
                        path=ACCESS_PATH, **common)
    if refresh:
        resp.set_cookie(REFRESH, refresh, max_age=int(jwt["REFRESH_TOKEN_LIFETIME"].total_seconds()),
                        path=REFRESH_PATH, **common)


def clear_auth_cookies(resp):
    resp.delete_cookie(ACCESS, path=ACCESS_PATH, samesite="Strict")
    resp.delete_cookie(REFRESH, path=REFRESH_PATH, samesite="Strict")


class _Public(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]


class CsrfView(_Public):
    def get(self, request):
        get_token(request)  # makes CsrfViewMiddleware set the csrftoken cookie
        return Response({"ok": True})


class LoginView(_Public):
    throttle_scope = "login"

    def post(self, request):
        enforce_csrf(request)
        ser = TokenObtainPairSerializer(data=request.data)
        try:
            ser.is_valid(raise_exception=True)
        except (AuthenticationFailed, ValidationError):
            return Response({"detail": "Invalid username or password."}, status=401)
        resp = Response({"username": ser.user.get_username()})
        set_auth_cookies(resp, ser.validated_data["access"], ser.validated_data["refresh"])
        return resp


class RefreshView(_Public):
    def post(self, request):
        enforce_csrf(request)
        raw = request.COOKIES.get(REFRESH)
        ser = TokenRefreshSerializer(data={"refresh": raw or ""})
        try:
            if not raw:
                raise TokenError("missing")
            ser.is_valid(raise_exception=True)
        except (TokenError, ValidationError, AuthenticationFailed):
            resp = Response({"detail": "Session expired."}, status=401)
            clear_auth_cookies(resp)
            return resp
        resp = Response({"ok": True})
        set_auth_cookies(resp, ser.validated_data["access"], ser.validated_data.get("refresh"))
        return resp


class LogoutView(_Public):
    def post(self, request):
        enforce_csrf(request)
        raw = request.COOKIES.get(REFRESH)
        if raw:
            try:
                RefreshToken(raw).blacklist()  # revoke server-side, not just client-side
            except TokenError:
                pass
        resp = Response(status=204)
        clear_auth_cookies(resp)
        return resp


class MeView(APIView):
    def get(self, request):
        return Response({"username": request.user.get_username()})
