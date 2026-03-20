import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.utils.text import slugify


class ThePeachAuthError(Exception):
    pass


@dataclass(frozen=True)
class PlatformUser:
    id: str
    email: str
    display_name: str
    full_name: str
    first_name: str
    last_name: str
    is_active: bool

    @classmethod
    def from_dict(cls, payload: dict | None):
        data = payload or {}
        return cls(
            id=str(data.get("id") or ""),
            email=(data.get("email") or "").strip(),
            display_name=(data.get("display_name") or "").strip(),
            full_name=(data.get("full_name") or "").strip(),
            first_name=(data.get("first_name") or "").strip(),
            last_name=(data.get("last_name") or "").strip(),
            is_active=bool(data.get("is_active", True)),
        )

    @property
    def preferred_name(self) -> str:
        return self.display_name or self.full_name or self.email


def _build_url(path: str) -> str:
    return f"{settings.THEPEACH_AUTH_BASE_URL}{path}"


def _build_login_url(path: str) -> str:
    return f"{settings.THEPEACH_LOGIN_BASE_URL}{path}"


def _build_headers(*, access_token: str = "", include_json: bool = False) -> dict:
    headers = {"Accept": "application/json"}
    if include_json:
        headers["Content-Type"] = "application/json"
    upstream_host = getattr(settings, "THEPEACH_UPSTREAM_HOST_HEADER", "").strip()
    if upstream_host:
        headers["Host"] = upstream_host
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _extract_error_message(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    detail = payload.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    if isinstance(detail, list) and detail:
        return " ".join(str(item) for item in detail if str(item).strip())
    if isinstance(detail, dict):
        for value in detail.values():
            if isinstance(value, list) and value:
                return " ".join(str(item) for item in value if str(item).strip())
            if isinstance(value, str) and value.strip():
                return value.strip()
    for value in payload.values():
        if isinstance(value, list) and value:
            return " ".join(str(item) for item in value if str(item).strip())
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _decode_success(response) -> dict:
    body = response.read().decode("utf-8")
    payload = json.loads(body or "{}")
    if not isinstance(payload, dict):
        raise ThePeachAuthError("ThePeach 응답 형식이 올바르지 않습니다.")
    if payload.get("success") is False:
        error = payload.get("error") or {}
        raise ThePeachAuthError(error.get("message") or "ThePeach 인증 요청이 실패했습니다.")
    return payload.get("data") or {}


def _request_json(path: str, *, method: str = "GET", data: dict | None = None, access_token: str = "", base_url_builder=_build_url) -> dict:
    headers = _build_headers(access_token=access_token, include_json=data is not None)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
    request = Request(base_url_builder(path), data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=settings.THEPEACH_AUTH_TIMEOUT) as response:
            return _decode_success(response)
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            payload = {}
        message = _extract_error_message(payload) or f"ThePeach 인증 서버가 요청을 거부했습니다. (HTTP {exc.code})"
        raise ThePeachAuthError(message) from exc
    except URLError as exc:
        raise ThePeachAuthError("ThePeach 인증 서버에 연결할 수 없습니다.") from exc


def login_with_thepeach(*, email: str, password: str) -> dict:
    return _request_json(
        settings.THEPEACH_LOGIN_PATH,
        method="POST",
        data={"email": email, "password": password},
        base_url_builder=_build_login_url,
    )


def signup_with_thepeach(*, email: str, full_name: str, smartphone_number: str, password: str) -> dict:
    return _request_json(
        settings.THEPEACH_SIGNUP_PATH,
        method="POST",
        data={
            "email": email,
            "full_name": full_name,
            "smartphone_number": smartphone_number,
            "password": password,
        },
        base_url_builder=_build_login_url,
    )


def refresh_thepeach_access_token(*, refresh_token: str) -> dict:
    return _request_json(
        settings.THEPEACH_REFRESH_PATH,
        method="POST",
        data={"refresh": refresh_token},
        base_url_builder=_build_login_url,
    )


def fetch_thepeach_profile(*, access_token: str) -> PlatformUser:
    return PlatformUser.from_dict(
        _request_json(
            settings.THEPEACH_PROFILE_PATH,
            method="GET",
            access_token=access_token,
        )
    )


def logout_from_thepeach(*, access_token: str, refresh_token: str) -> None:
    _request_json(
        settings.THEPEACH_LOGOUT_PATH,
        method="POST",
        data={"refresh": refresh_token},
        access_token=access_token,
        base_url_builder=_build_login_url,
    )


def _generate_username(email: str, full_name: str) -> str:
    candidate = (email or "").strip()
    if candidate:
        return candidate
    candidate = slugify(full_name or "")
    return candidate or "thepeach-user"


@transaction.atomic
def sync_local_user(platform_user: PlatformUser):
    user_model = get_user_model()
    email = platform_user.email
    defaults = {
        "email": email,
        "first_name": platform_user.first_name,
        "last_name": platform_user.last_name,
        "is_active": platform_user.is_active,
    }
    username = _generate_username(email, platform_user.preferred_name)
    local_user = user_model.objects.filter(email=email).order_by("id").first()
    if local_user is None:
        base_username = username
        suffix = 1
        while user_model.objects.filter(username=username).exists():
            suffix += 1
            username = f"{base_username}-{suffix}"
        local_user = user_model.objects.create_user(
            username=username,
            email=email,
            password=None,
        )
        if isinstance(local_user, AbstractBaseUser):
            local_user.set_unusable_password()
    if hasattr(local_user, "email"):
        local_user.email = email
    if hasattr(local_user, "first_name"):
        local_user.first_name = platform_user.first_name
    if hasattr(local_user, "last_name"):
        local_user.last_name = platform_user.last_name
    if hasattr(local_user, "is_active"):
        local_user.is_active = platform_user.is_active
    if not getattr(local_user, "username", "").strip():
        local_user.username = username
    local_user.save()
    return local_user
