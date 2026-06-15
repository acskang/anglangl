#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_MIGRATIONS=1

log() {
  printf '[pg-min] %s\n' "$*"
}

die() {
  printf '[pg-min] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  scripts/test-postgres-min.sh [--skip-migrate] [django-test-label...]

Purpose:
  Run the minimum PostgreSQL-backed regression path for anglangl.

Default test labels:
  core.tests
  study.tests
  dashboard.tests
  dramaNlearn.tests

Environment overrides:
  DATABASE_URL
  DJANGO_SETTINGS_MODULE
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
  export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.local}"
  export SECRET_KEY="${SECRET_KEY:-dev-secret-key}"
  export DEBUG="${DEBUG:-True}"
  export ALLOWED_HOSTS="${ALLOWED_HOSTS:-127.0.0.1,localhost}"
  export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:ths5rhd@127.0.0.1:5432/listening_clips}"
}

for arg in "$@"; do
  case "$arg" in
    --skip-migrate)
      RUN_MIGRATIONS=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      break
      ;;
  esac
done

cd "$ROOT_DIR"
ensure_venv
export_defaults

TEST_LABELS=("$@")
if [[ "${#TEST_LABELS[@]}" -eq 0 ]]; then
  TEST_LABELS=(core.tests study.tests dashboard.tests dramaNlearn.tests)
fi

DB_HOST="$(python - <<'PY'
from urllib.parse import urlparse
import os
parsed = urlparse(os.environ["DATABASE_URL"])
print(parsed.hostname or "127.0.0.1")
PY
)"
DB_PORT="$(python - <<'PY'
from urllib.parse import urlparse
import os
parsed = urlparse(os.environ["DATABASE_URL"])
print(parsed.port or 5432)
PY
)"
DB_NAME="$(python - <<'PY'
from urllib.parse import urlparse
import os
parsed = urlparse(os.environ["DATABASE_URL"])
print(parsed.path.lstrip("/") or "")
PY
)"
DB_USER="$(python - <<'PY'
from urllib.parse import urlparse
import os
parsed = urlparse(os.environ["DATABASE_URL"])
print(parsed.username or "")
PY
)"
DB_PASSWORD="$(python - <<'PY'
from urllib.parse import urlparse
import os
parsed = urlparse(os.environ["DATABASE_URL"])
print(parsed.password or "")
PY
)"

if ! PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c 'select 1;' >/dev/null 2>&1; then
  die "PostgreSQL login failed for $DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
fi

log "Running Django system check against PostgreSQL"
python "$ROOT_DIR/manage.py" check

if [[ "$RUN_MIGRATIONS" == "1" ]]; then
  log "Applying migrations against PostgreSQL"
  python "$ROOT_DIR/manage.py" migrate --noinput
else
  log "Skipping migrations because --skip-migrate was provided"
fi

log "Running tests: ${TEST_LABELS[*]}"
python "$ROOT_DIR/manage.py" test "${TEST_LABELS[@]}"
