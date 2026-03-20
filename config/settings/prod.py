from .base import *  # noqa

from django.core.exceptions import ImproperlyConfigured

DEBUG = False

if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY must be set in production.")
if not DJANGO_INTERNAL_API_TOKEN:
    raise ImproperlyConfigured("DJANGO_INTERNAL_API_TOKEN must be set in production.")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set in production.")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
