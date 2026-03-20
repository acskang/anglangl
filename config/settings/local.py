from .base import *  # noqa

DEBUG = True
SECRET_KEY = SECRET_KEY or "dev-secret-key"
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:8000", "http://localhost:8000"]

if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql" and not DATABASES["default"]["PASSWORD"]:
    DATABASES["default"]["PASSWORD"] = "ths5rhd"
