import os

from .base import *  # noqa

from django.core.exceptions import ImproperlyConfigured


def _prod_env(name: str, default=None, *, legacy_names: tuple[str, ...] = ()):
    for candidate in (name, *legacy_names):
        value = os.environ.get(candidate)
        if value not in {None, ""}:
            return value
    return default


def _prod_env_bool(name: str, default: bool = False) -> bool:
    return str(_prod_env(name, str(default))).lower() in {"1", "true", "yes", "on"}

DEBUG = False

if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY or SECRET_KEY must be set in production.")
if not DJANGO_INTERNAL_API_TOKEN:
    raise ImproperlyConfigured("DJANGO_INTERNAL_API_TOKEN must be set in production.")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS or ALLOWED_HOSTS must be set in production.")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = _prod_env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = int(_prod_env("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _prod_env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
SECURE_HSTS_PRELOAD = _prod_env_bool("DJANGO_SECURE_HSTS_PRELOAD", True)
