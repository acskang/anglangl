#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUIRE_WORKER=0
REQUIRE_MCP_ENV=0
FAILURES=0

log() {
  printf '[dev-check] %s\n' "$*"
}

pass() {
  printf '[dev-check] PASS: %s\n' "$*"
}

warn() {
  printf '[dev-check] WARN: %s\n' "$*"
}

fail() {
  printf '[dev-check] FAIL: %s\n' "$*" >&2
  FAILURES=$((FAILURES + 1))
}

usage() {
  cat <<'EOF'
Usage:
  scripts/dev-check.sh [--require-worker] [--require-mcp-env]

Checks:
  - required commands on PATH
  - PostgreSQL reachability from DATABASE_URL
  - Redis reachability from CELERY_BROKER_URL
  - Django settings/import health
  - database connectivity
  - Celery app import
  - optional Celery worker ping
  - optional MCP environment completeness
EOF
}

ensure_venv() {
  if [[ -z "${VIRTUAL_ENV:-}" && -f "$ROOT_DIR/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.venv/bin/activate"
    log "Activated virtualenv at $ROOT_DIR/.venv"
  fi
}

export_defaults() {
  export SECRET_KEY="${SECRET_KEY:-dev-secret-key}"
  export DEBUG="${DEBUG:-True}"
  export ALLOWED_HOSTS="${ALLOWED_HOSTS:-127.0.0.1,localhost}"
  export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:5432/listen_practice}"
  export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://127.0.0.1:6379/0}"
  export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://127.0.0.1:6379/1}"
  export STATIC_ROOT="${STATIC_ROOT:-$ROOT_DIR/staticfiles}"
  export MEDIA_ROOT="${MEDIA_ROOT:-$ROOT_DIR/media}"
  export DJANGO_INTERNAL_API_TOKEN="${DJANGO_INTERNAL_API_TOKEN:-}"
  export INTERNAL_PLAYBACK_LINK_TTL_SECONDS="${INTERNAL_PLAYBACK_LINK_TTL_SECONDS:-900}"
  export DJANGO_API_BASE_URL="${DJANGO_API_BASE_URL:-http://127.0.0.1:8000}"
  export MCP_PUBLIC_BASE_URL="${MCP_PUBLIC_BASE_URL:-http://127.0.0.1:3000}"
  export DJANGO_USER_HEADER_NAME="${DJANGO_USER_HEADER_NAME:-X-Internal-User-Id}"
  export DJANGO_DEFAULT_USER_ID="${DJANGO_DEFAULT_USER_ID:-1}"
  export DJANGO_API_TIMEOUT_SECONDS="${DJANGO_API_TIMEOUT_SECONDS:-10}"
}

for arg in "$@"; do
  case "$arg" in
    --require-worker)
      REQUIRE_WORKER=1
      ;;
    --require-mcp-env)
      REQUIRE_MCP_ENV=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $arg"
      usage
      exit 1
      ;;
  esac
done

cd "$ROOT_DIR"
ensure_venv
export_defaults

for cmd in python celery redis-cli pg_isready yt-dlp ffmpeg ffprobe; do
  if command -v "$cmd" >/dev/null 2>&1; then
    pass "Command available: $cmd"
  else
    fail "Missing command: $cmd"
  fi
done

DB_HOST="$(python - <<'PY'
from urllib.parse import urlparse
import os
url = os.environ["DATABASE_URL"]
parsed = urlparse(url)
print(parsed.hostname or "127.0.0.1")
PY
)"
DB_PORT="$(python - <<'PY'
from urllib.parse import urlparse
import os
url = os.environ["DATABASE_URL"]
parsed = urlparse(url)
print(parsed.port or 5432)
PY
)"
DB_NAME="$(python - <<'PY'
from urllib.parse import urlparse
import os
url = os.environ["DATABASE_URL"]
parsed = urlparse(url)
print(parsed.path.lstrip("/") or "")
PY
)"

if pg_isready -h "$DB_HOST" -p "$DB_PORT" >/dev/null 2>&1; then
  pass "PostgreSQL reachable at $DB_HOST:$DB_PORT"
else
  fail "PostgreSQL not reachable at $DB_HOST:$DB_PORT"
fi

if redis-cli -u "$CELERY_BROKER_URL" ping >/dev/null 2>&1; then
  pass "Redis reachable at $CELERY_BROKER_URL"
else
  fail "Redis not reachable at $CELERY_BROKER_URL"
fi

if python "$ROOT_DIR/manage.py" check >/dev/null; then
  pass "Django settings check passed"
else
  fail "python manage.py check failed"
fi

if python "$ROOT_DIR/manage.py" shell -c "from django.db import connection; connection.ensure_connection(); print(connection.vendor)" >/dev/null 2>&1; then
  pass "Django database connection succeeded for $DB_NAME"
else
  fail "Django could not connect to database $DB_NAME"
fi

if python - <<'PY' >/dev/null
from config.celery import app
assert app.main == "config"
PY
then
  pass "Celery app import succeeded"
else
  fail "Celery app import failed"
fi

if celery -A config inspect ping >/dev/null 2>&1; then
  pass "At least one Celery worker responded to inspect ping"
else
  if [[ "$REQUIRE_WORKER" == "1" ]]; then
    fail "No Celery worker responded to inspect ping"
  else
    warn "No Celery worker responded to inspect ping"
  fi
fi

if [[ "$REQUIRE_MCP_ENV" == "1" ]]; then
  if [[ -n "$DJANGO_INTERNAL_API_TOKEN" ]]; then
    pass "DJANGO_INTERNAL_API_TOKEN is set"
  else
    fail "DJANGO_INTERNAL_API_TOKEN is required for MCP/internal API checks"
  fi

  if python - <<'PY' >/dev/null
import importlib
mod = importlib.import_module("mcp_server.server")
assert hasattr(mod, "mcp")
PY
  then
    pass "MCP server import succeeded"
  else
    fail "MCP server import failed"
  fi
fi

if [[ "$FAILURES" -gt 0 ]]; then
  log "Completed with $FAILURES failure(s)"
  exit 1
fi

log "All checks passed"
