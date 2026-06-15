import logging

from django.conf import settings
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout

from .cookies import clear_thepeach_auth_cookies, set_thepeach_auth_cookies
from .services import ThePeachAuthError, fetch_thepeach_profile, refresh_thepeach_access_token, sync_local_user
from .session import clear_thepeach_session, is_thepeach_session, needs_thepeach_session_store, store_thepeach_session

auth_logger = logging.getLogger("platform_auth")


class ThePeachSSOMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request._thepeach_cookie_operation = None
        self._authenticate_from_shared_cookie(request)
        response = self.get_response(request)
        operation = getattr(request, "_thepeach_cookie_operation", None)
        if operation == "clear":
            clear_thepeach_auth_cookies(response)
        elif operation and operation[0] == "set":
            set_thepeach_auth_cookies(response, access_token=operation[1], refresh_token=operation[2])
        return response

    def _authenticate_from_shared_cookie(self, request):
        if request.path.endswith("/logout/"):
            return

        access_token = request.COOKIES.get(settings.THEPEACH_SSO_ACCESS_COOKIE_NAME, "").strip()
        refresh_token = request.COOKIES.get(settings.THEPEACH_SSO_REFRESH_COOKIE_NAME, "").strip()
        auth_logger.info(
            "sso_request_started path=%s local_authenticated=%s access_cookie=%s refresh_cookie=%s",
            request.path,
            bool(getattr(request.user, "is_authenticated", False)),
            bool(access_token),
            bool(refresh_token),
        )

        if not access_token:
            if getattr(request.user, "is_authenticated", False) and is_thepeach_session(request):
                auth_logout(request)
                clear_thepeach_session(request)
                auth_logger.info("sso_request_missing_cookie_logging_out path=%s", request.path)
            return

        try:
            profile = fetch_thepeach_profile(access_token=access_token)
        except ThePeachAuthError:
            if not refresh_token:
                self._clear_auth(request)
                return
            auth_logger.info("sso_request_refresh_started path=%s", request.path)
            try:
                auth_data = refresh_thepeach_access_token(refresh_token=refresh_token)
                access_token = auth_data.get("access", "")
                refresh_token = auth_data.get("refresh", "")
                if not access_token or not refresh_token:
                    raise ThePeachAuthError("ThePeach refresh 응답에 토큰이 없습니다.")
                request._thepeach_cookie_operation = ("set", access_token, refresh_token)
                profile = fetch_thepeach_profile(access_token=access_token)
            except ThePeachAuthError as exc:
                auth_logger.warning("sso_request_refresh_failed path=%s detail=%s", request.path, exc)
                self._clear_auth(request)
                return

        profile_payload = {
            "id": profile.id,
            "email": profile.email,
            "display_name": profile.display_name,
            "full_name": profile.full_name,
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "is_active": profile.is_active,
        }
        local_user = sync_local_user(profile)
        reused_session = self._can_reuse_thepeach_login(request, local_user)
        if not reused_session:
            auth_login(request, local_user, backend="django.contrib.auth.backends.ModelBackend")
        if not reused_session or needs_thepeach_session_store(
            request=request,
            access_token=access_token,
            refresh_token=refresh_token,
            profile=profile_payload,
        ):
            store_thepeach_session(
                request=request,
                access_token=access_token,
                refresh_token=refresh_token,
                profile=profile_payload,
            )
        request.user = local_user
        auth_logger.info(
            "sso_request_authenticated path=%s user_id=%s email=%s reused_session=%s",
            request.path,
            local_user.id,
            local_user.email,
            reused_session,
        )

    def _can_reuse_thepeach_login(self, request, local_user) -> bool:
        if not getattr(request.user, "is_authenticated", False):
            return False
        if getattr(request.user, "pk", None) != local_user.pk:
            return False
        return is_thepeach_session(request)

    def _clear_auth(self, request):
        if getattr(request.user, "is_authenticated", False) and is_thepeach_session(request):
            auth_logout(request)
        clear_thepeach_session(request)
        request._thepeach_cookie_operation = "clear"
