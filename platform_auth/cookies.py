from django.conf import settings


def set_thepeach_auth_cookies(response, *, access_token: str, refresh_token: str) -> None:
    common = {
        "domain": settings.THEPEACH_SSO_COOKIE_DOMAIN or None,
        "path": settings.THEPEACH_SSO_COOKIE_PATH,
        "secure": getattr(settings, "SESSION_COOKIE_SECURE", False),
        "httponly": True,
        "samesite": settings.THEPEACH_SSO_COOKIE_SAMESITE,
    }
    response.set_cookie(settings.THEPEACH_SSO_ACCESS_COOKIE_NAME, access_token, **common)
    response.set_cookie(settings.THEPEACH_SSO_REFRESH_COOKIE_NAME, refresh_token, **common)


def clear_thepeach_auth_cookies(response) -> None:
    common = {
        "domain": settings.THEPEACH_SSO_COOKIE_DOMAIN or None,
        "path": settings.THEPEACH_SSO_COOKIE_PATH,
        "samesite": settings.THEPEACH_SSO_COOKIE_SAMESITE,
    }
    response.delete_cookie(settings.THEPEACH_SSO_ACCESS_COOKIE_NAME, **common)
    response.delete_cookie(settings.THEPEACH_SSO_REFRESH_COOKIE_NAME, **common)
