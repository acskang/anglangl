import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("SECRET_KEY", "")
DEBUG = _env_bool("DEBUG", False)

ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = _env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "platform_auth",
    "core",
    "videos",
    "clips",
    "study",
    "interactions",
    "workers",
    "dashboard",
    "youtube_saver",
    "internal_api",
    "dramaNlearn",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


def _database_from_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme == "sqlite":
        db_path = parsed.path or "/db.sqlite3"
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": db_path,
        }
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
    }


database_url = os.environ.get("DATABASE_URL")
use_sqlite = _env_bool("USE_SQLITE", False)
if use_sqlite:
    default_db = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / os.environ.get("SQLITE_NAME", "db.sqlite3"),
    }
elif database_url:
    default_db = _database_from_url(database_url)
else:
    default_db = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "listening_clips"),
        "USER": os.environ.get("POSTGRES_USER", "cskang"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }

DATABASES = {"default": default_db}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = os.environ.get("STATIC_URL", "/static/")
STATIC_ROOT = Path(os.environ.get("STATIC_ROOT", BASE_DIR / "staticfiles"))
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = os.environ.get("MEDIA_URL", "/media/")
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.environ.get("CSRF_COOKIE_SAMESITE", "Lax")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = os.environ.get("X_FRAME_OPTIONS", "DENY")
SECURE_REFERRER_POLICY = os.environ.get("SECURE_REFERRER_POLICY", "same-origin")

THEPEACH_AUTH_BASE_URL = os.environ.get("THEPEACH_AUTH_BASE_URL", "http://127.0.0.1").rstrip("/")
THEPEACH_LOGIN_BASE_URL = os.environ.get("THEPEACH_LOGIN_BASE_URL", THEPEACH_AUTH_BASE_URL).rstrip("/")
THEPEACH_UPSTREAM_HOST_HEADER = os.environ.get("THEPEACH_UPSTREAM_HOST_HEADER", "thepeach.thesysm.com").strip()
THEPEACH_SIGNUP_PATH = os.environ.get("THEPEACH_SIGNUP_PATH", "/api/v1/auth/signup/")
THEPEACH_LOGIN_PATH = os.environ.get("THEPEACH_LOGIN_PATH", "/api/v1/auth/login/")
THEPEACH_REFRESH_PATH = os.environ.get("THEPEACH_REFRESH_PATH", "/api/v1/auth/token/refresh/")
THEPEACH_LOGOUT_PATH = os.environ.get("THEPEACH_LOGOUT_PATH", "/api/v1/auth/logout/")
THEPEACH_PROFILE_PATH = os.environ.get("THEPEACH_PROFILE_PATH", "/api/v1/auth/me/")
THEPEACH_AUTH_TIMEOUT = int(os.environ.get("THEPEACH_AUTH_TIMEOUT", "10"))

LOGIN_URL = "platform_auth:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "landing"

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_SOFT_TIME_LIMIT = int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", str(45 * 60)))
CELERY_TASK_TIME_LIMIT = int(os.environ.get("CELERY_TASK_TIME_LIMIT", str(50 * 60)))
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    "videos.tasks.download_youtube_video": {"queue": "youtube_download"},
    "clips.tasks.extract_clip": {"queue": "clip_extract"},
    "clips.tasks.process_uploaded_clip": {"queue": "clip_upload_process"},
}
CELERY_FFMPEG_SOFT_TIME_LIMIT = int(
    os.environ.get("CELERY_FFMPEG_SOFT_TIME_LIMIT", str(CELERY_TASK_SOFT_TIME_LIMIT))
)
CELERY_FFMPEG_TIME_LIMIT = int(os.environ.get("CELERY_FFMPEG_TIME_LIMIT", str(CELERY_TASK_TIME_LIMIT)))
FFMPEG_DEFAULT_TIMEOUT = int(os.environ.get("FFMPEG_DEFAULT_TIMEOUT", str(45 * 60)))
FFMPEG_HLS_TIMEOUT = int(os.environ.get("FFMPEG_HLS_TIMEOUT", str(60 * 60)))

CLIP_UPLOAD_MAX_FILES_PER_BATCH = int(os.environ.get("CLIP_UPLOAD_MAX_FILES_PER_BATCH", "30"))
CLIP_UPLOAD_MAX_FILE_SIZE_BYTES = int(os.environ.get("CLIP_UPLOAD_MAX_FILE_SIZE_BYTES", str(300 * 1024 * 1024)))
CLIP_UPLOAD_ALLOWED_EXTENSIONS = os.environ.get(
    "CLIP_UPLOAD_ALLOWED_EXTENSIONS",
    ".mp4,.mov,.mkv,.webm,.m4v",
).split(",")

DJANGO_INTERNAL_API_TOKEN = os.environ.get("DJANGO_INTERNAL_API_TOKEN", "")
INTERNAL_PLAYBACK_LINK_TTL_SECONDS = int(os.environ.get("INTERNAL_PLAYBACK_LINK_TTL_SECONDS", "900"))
KOBIS_API_KEY = os.environ.get("KOBIS_API_KEY", "")
