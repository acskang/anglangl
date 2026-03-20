import secrets
from typing import Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest, JsonResponse


AUTH_USER_HEADER = "X-Internal-User-Id"


def _extract_bearer_token(request: HttpRequest) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip()


def resolve_internal_user(request: HttpRequest):
    expected_token = getattr(settings, "DJANGO_INTERNAL_API_TOKEN", "")
    provided_token = _extract_bearer_token(request)

    if not expected_token or not provided_token:
        return AnonymousUser()

    if not secrets.compare_digest(expected_token, provided_token):
        return AnonymousUser()

    user_id_raw = request.headers.get(AUTH_USER_HEADER, "").strip()
    if not user_id_raw.isdigit():
        return AnonymousUser()

    user_model = get_user_model()
    user = user_model.objects.filter(id=int(user_id_raw), is_active=True).first()
    return user or AnonymousUser()


def require_internal_user(request: HttpRequest):
    user = resolve_internal_user(request)
    if not user.is_authenticated:
        return None, JsonResponse({"error": "authentication_required"}, status=401)
    return user, None
