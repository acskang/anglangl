#!/usr/bin/env bash
# Development launcher for the local ListenTube stack.
#
# This script is intentionally opinionated:
# - It assumes Django runs from this repository root.
# - It assumes Celery uses the project's real queue names.
# - It does not try to start PostgreSQL or Redis itself because that often
#   requires system-specific privileges or service managers.
# - It delegates environment and infrastructure validation to dev-check.sh
#   before starting application processes.
#
# Supported workflows:
# - full:   preflight -> migrate -> background Celery -> foreground Django
# - django: preflight -> migrate -> foreground Django
# - celery: preflight -> foreground Celery
# - mcp:    preflight (with MCP env checks) -> foreground MCP stdio server
set -euo pipefail

# Resolve the repository root relative to this script location so the script
# keeps working no matter which directory the user launches it from.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Mode controls which process topology to launch.
MODE="${1:-full}"

# Default bind address for Django's dev server.
DJANGO_BIND="${DJANGO_BIND:-127.0.0.1:8000}"

# One worker can serve all queues in development. The queue list here matches
# the actual queue routing configured in config/settings/base.py.
CELERY_QUEUES="${CELERY_QUEUES:-default,youtube_download,clip_extract,clip_upload_process}"

# Migrations are enabled by default because a stale schema is one of the most
# common local startup issues during development.
RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"

# Populated only when "full" mode starts a background worker.
CELERY_PID=""

log() {
  printf '[dev-up] %s\n' "$*"
}

die() {
  printf '[dev-up] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  scripts/dev-up.sh [full|django|celery|mcp]

Modes:
  full    Run migrations, start one Celery worker in background, run Django in foreground.
  django  Run migrations, then run Django only.
  celery  Run one Celery worker in foreground.
  mcp     Run the MCP server in foreground.

Environment overrides:
  DATABASE_URL
  CELERY_BROKER_URL
  CELERY_RESULT_BACKEND
  DJANGO_BIND
  CELERY_QUEUES
  RUN_MIGRATIONS=0
  DJANGO_INTERNAL_API_TOKEN
  DJANGO_API_BASE_URL
  DJANGO_DEFAULT_USER_ID
EOF
}

# If the user has a repo-local virtualenv but forgot to activate it, activate
# it automatically. This keeps local startup ergonomic without forcing a
# specific environment manager on the user.
ensure_venv() {
  if [[ -z "${VIRTUAL_ENV:-}" && -f "$ROOT_DIR/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.venv/bin/activate"
    log "Activated virtualenv at $ROOT_DIR/.venv"
  fi
}

# Export development defaults that mirror the real codebase expectations.
# Every value can still be overridden by the caller's environment.
#
# The goal is:
# - make local startup work with minimal typing
# - avoid hidden dependency on an external .env loader
# - centralize the defaults in one place so they are easy to audit
export_defaults() {
  export SECRET_KEY="${SECRET_KEY:-dev-secret-key}"
  export DEBUG="${DEBUG:-True}"
  export ALLOWED_HOSTS="${ALLOWED_HOSTS:-127.0.0.1,localhost}"
  export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:ths5rhd@127.0.0.1:5432/listening_clips}"
  export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://127.0.0.1:6379/0}"
  export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://127.0.0.1:6379/1}"
  export STATIC_URL="${STATIC_URL:-/static/}"
  export STATIC_ROOT="${STATIC_ROOT:-$ROOT_DIR/staticfiles}"
  export MEDIA_URL="${MEDIA_URL:-/media/}"
  export MEDIA_ROOT="${MEDIA_ROOT:-$ROOT_DIR/media}"
  export CLIP_UPLOAD_MAX_FILES_PER_BATCH="${CLIP_UPLOAD_MAX_FILES_PER_BATCH:-30}"
  export CLIP_UPLOAD_MAX_FILE_SIZE_BYTES="${CLIP_UPLOAD_MAX_FILE_SIZE_BYTES:-314572800}"
  export CLIP_UPLOAD_ALLOWED_EXTENSIONS="${CLIP_UPLOAD_ALLOWED_EXTENSIONS:-.mp4,.mov,.mkv,.webm,.m4v}"
  export DJANGO_INTERNAL_API_TOKEN="${DJANGO_INTERNAL_API_TOKEN:-replace-with-strong-token}"
  export INTERNAL_PLAYBACK_LINK_TTL_SECONDS="${INTERNAL_PLAYBACK_LINK_TTL_SECONDS:-900}"
  export DJANGO_API_BASE_URL="${DJANGO_API_BASE_URL:-http://127.0.0.1:8000}"
  export MCP_PUBLIC_BASE_URL="${MCP_PUBLIC_BASE_URL:-http://127.0.0.1:3000}"
  export DJANGO_USER_HEADER_NAME="${DJANGO_USER_HEADER_NAME:-X-Internal-User-Id}"
  export DJANGO_DEFAULT_USER_ID="${DJANGO_DEFAULT_USER_ID:-1}"
  export DJANGO_API_TIMEOUT_SECONDS="${DJANGO_API_TIMEOUT_SECONDS:-10}"

  mkdir -p "$STATIC_ROOT" "$MEDIA_ROOT" "$ROOT_DIR/.dev"
}

# Clean up any background process this script started itself.
# We only manage the Celery PID created in "full" mode. Django runs in the
# foreground, and the MCP mode intentionally uses exec so it replaces the shell
# process instead of becoming an unmanaged child.
cleanup() {
  if [[ -n "$CELERY_PID" ]] && kill -0 "$CELERY_PID" >/dev/null 2>&1; then
    log "Stopping Celery worker ($CELERY_PID)"
    kill "$CELERY_PID" >/dev/null 2>&1 || true
    wait "$CELERY_PID" 2>/dev/null || true
  fi
}

# Run the shared validation script before we do anything expensive.
# This catches missing binaries, dead Redis/Postgres, broken settings, or bad
# DB connectivity before the user stares at a half-started stack.
preflight() {
  "$ROOT_DIR/scripts/dev-check.sh" "$@"
}

# Keep schema state aligned with the code before starting the web server.
# In active development this is generally the safest default.
run_migrations() {
  if [[ "$RUN_MIGRATIONS" == "1" ]]; then
    log "Running migrations"
    python "$ROOT_DIR/manage.py" migrate
  else
    log "Skipping migrations because RUN_MIGRATIONS=0"
  fi
}

# Start a single background Celery worker and keep a PID so the script can
# clean it up automatically when the foreground Django server exits.
# Worker output goes to .dev/celery.log to keep the main terminal readable.
start_celery_background() {
  local logfile="$ROOT_DIR/.dev/celery.log"
  log "Starting Celery worker in background for queues: $CELERY_QUEUES"
  celery -A config worker -l info -Q "$CELERY_QUEUES" >"$logfile" 2>&1 &
  CELERY_PID=$!
  sleep 2
  if ! kill -0 "$CELERY_PID" >/dev/null 2>&1; then
    die "Celery worker exited immediately. Check $logfile"
  fi
  log "Celery worker PID=$CELERY_PID log=$logfile"
}

# Run Django in the foreground so Ctrl+C behaves like a normal local dev
# session and the caller sees request logs directly.
run_django() {
  log "Starting Django on http://$DJANGO_BIND/"
  python "$ROOT_DIR/manage.py" runserver "$DJANGO_BIND"
}

# Foreground worker mode is useful when the user wants to inspect task logs
# live in the current terminal or run Celery separately from Django.
run_celery_foreground() {
  log "Starting Celery worker in foreground for queues: $CELERY_QUEUES"
  exec celery -A config worker -l info -Q "$CELERY_QUEUES"
}

# The current MCP entrypoint uses FastMCP's default stdio transport.
# That means it should run in the foreground and be attached directly to the
# host/client process that speaks MCP, not backgrounded like a normal HTTP app.
run_mcp() {
  log "Starting MCP server via stdio transport"
  exec python -m mcp_server.server
}

# Support --help anywhere in the argument list so both
#   scripts/dev-up.sh --help
# and
#   scripts/dev-up.sh mcp --help
# behave intuitively.
for arg in "$@"; do
  if [[ "$arg" == "-h" || "$arg" == "--help" ]]; then
    usage
    exit 0
  fi
done

case "$MODE" in
  full|django|celery|mcp)
    ;;
  *)
    usage
    die "Unknown mode: $MODE"
    ;;
esac

# Normalize into the repo root before invoking manage.py or any relative paths.
cd "$ROOT_DIR"
ensure_venv
export_defaults

# MCP mode is handled early because it has slightly different validation needs:
# we require MCP-related env to be present, then replace the shell with the MCP
# server process immediately.
if [[ "$MODE" == "mcp" ]]; then
  preflight --require-mcp-env
  run_mcp
fi

# In modes that start a background worker, make sure it is stopped when the
# script exits for any reason.
trap cleanup EXIT INT TERM

# Shared validation for Django/Celery-oriented modes.
preflight

# Main mode dispatcher.
case "$MODE" in
  full)
    # Full local app mode:
    # 1. apply migrations
    # 2. start Celery in background
    # 3. run Django in foreground
    run_migrations
    start_celery_background
    run_django
    ;;
  django)
    # Web-only mode:
    # useful for template/view work where background jobs are not needed.
    run_migrations
    run_django
    ;;
  celery)
    # Worker-only mode:
    # useful when Django is already running in another terminal.
    run_celery_foreground
    ;;
esac
