#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DJANGO_BASE_URL="${DJANGO_BASE_URL:-http://127.0.0.1:8000}"
REQUIRE_MCP=0
FAILURES=0

log() {
  printf '[dev-ready] %s\n' "$*"
}

pass() {
  printf '[dev-ready] PASS: %s\n' "$*"
}

warn() {
  printf '[dev-ready] WARN: %s\n' "$*"
}

fail() {
  printf '[dev-ready] FAIL: %s\n' "$*" >&2
  FAILURES=$((FAILURES + 1))
}

usage() {
  cat <<'EOF'
Usage:
  scripts/dev-ready.sh [--require-mcp]

Purpose:
  Run this in a second terminal after `scripts/dev-up.sh full`.
  It checks whether the local stack is actually ready for manual testing.

Checks:
  - shared infrastructure via scripts/dev-check.sh --require-worker
  - Django HTTP endpoints respond as expected
  - guest access to /dashboard/ redirects to login
  - optional MCP env/import checks

Environment overrides:
  DJANGO_BASE_URL=http://127.0.0.1:8000
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
  export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:ths5rhd@127.0.0.1:5432/listening_clips}"
  export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://127.0.0.1:6379/0}"
  export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://127.0.0.1:6379/1}"
  export DJANGO_INTERNAL_API_TOKEN="${DJANGO_INTERNAL_API_TOKEN:-}"
  export DJANGO_API_BASE_URL="${DJANGO_API_BASE_URL:-$DJANGO_BASE_URL}"
  export DJANGO_USER_HEADER_NAME="${DJANGO_USER_HEADER_NAME:-X-Internal-User-Id}"
  export DJANGO_DEFAULT_USER_ID="${DJANGO_DEFAULT_USER_ID:-1}"
}

check_http() {
  local path="$1"
  local expected_status="$2"
  local expected_text="${3:-}"

  local output
  if output="$(python - "$DJANGO_BASE_URL" "$path" "$expected_status" "$expected_text" 2>&1 <<'PY'
import sys
import urllib.error
import urllib.request

base_url, path, expected_status, expected_text = sys.argv[1:]
url = f"{base_url.rstrip('/')}{path}"
request = urllib.request.Request(url, headers={"User-Agent": "dev-ready-check"})

opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
try:
    response = opener.open(request, timeout=5)
    status = response.getcode()
    body = response.read().decode("utf-8", errors="ignore")
except urllib.error.HTTPError as exc:
    status = exc.code
    body = exc.read().decode("utf-8", errors="ignore")
except Exception as exc:
    raise SystemExit(f"network_error:{exc}")

if status != int(expected_status):
    raise SystemExit(f"unexpected_status:{status}")

if expected_text and expected_text not in body:
    raise SystemExit("missing_text")
PY
  )"; then
    pass "HTTP ${path} returned ${expected_status}"
  else
    fail "HTTP ${path} did not return expected status/text (${output})"
  fi
}

check_redirect_to_login() {
  local path="$1"

  local output
  if output="$(python - "$DJANGO_BASE_URL" "$path" 2>&1 <<'PY'
import sys
import urllib.error
import urllib.request

base_url, path = sys.argv[1:]
url = f"{base_url.rstrip('/')}{path}"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

opener = urllib.request.build_opener(NoRedirect)
request = urllib.request.Request(url, headers={"User-Agent": "dev-ready-check"})

try:
    opener.open(request, timeout=5)
    raise SystemExit("expected_redirect")
except urllib.error.HTTPError as exc:
    status = exc.code
    location = exc.headers.get("Location", "")
    if status not in (301, 302):
        raise SystemExit(f"unexpected_status:{status}")
    if "/auth/login/" not in location:
        raise SystemExit(f"unexpected_location:{location}")
except Exception as exc:
    raise SystemExit(f"network_error:{exc}")
PY
  )"; then
    pass "Guest access to ${path} redirects to login"
  else
    fail "Guest access to ${path} did not redirect to login (${output})"
  fi
}

for arg in "$@"; do
  case "$arg" in
    --require-mcp)
      REQUIRE_MCP=1
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

if "$ROOT_DIR/scripts/dev-check.sh" --require-worker $([[ "$REQUIRE_MCP" == "1" ]] && printf '%s' "--require-mcp-env"); then
  pass "Infrastructure and worker checks passed"
else
  fail "Infrastructure baseline is not ready"
fi

check_http "/" 200
check_http "/auth/login/" 200 "ThePeach Login"
check_http "/videos/" 302
check_http "/clips/" 302
check_redirect_to_login "/dashboard/"

if [[ "$REQUIRE_MCP" == "1" ]]; then
  if python - <<'PY' >/dev/null
import importlib
mod = importlib.import_module("mcp_server.server")
assert hasattr(mod, "mcp")
PY
  then
    pass "MCP module import is ready"
  else
    fail "MCP module import failed"
  fi
fi

if [[ "$FAILURES" -gt 0 ]]; then
  log "NOT READY: manual testing should wait until the failures above are fixed"
  exit 1
fi

log "READY: manual testing can start"
