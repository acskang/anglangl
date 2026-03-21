#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="/etc/anglangl/anglangl.env"
PYTHON_BIN="${PYTHON_BIN:-/home/cskang/miniconda3/envs/dj5/bin/python}"
PUBLIC_DOMAIN="${ANGLANGL_PUBLIC_DOMAIN:-anglangl.thesysm.com}"
USE_SQLITE_FALLBACK="${ANGLANGL_USE_SQLITE:-0}"
THEPEACH_PUBLIC_DOMAIN="${THEPEACH_PUBLIC_DOMAIN:-thepeach.thesysm.com}"
THEPEACH_ORIGIN_BASE_URL="${THEPEACH_ORIGIN_BASE_URL:-http://127.0.0.1}"

cd "$ROOT_DIR"

echo "[1/4] Refreshing production env file"

secret_key="$($PYTHON_BIN -c 'import secrets; print(secrets.token_urlsafe(50))')"
internal_api_token="$($PYTHON_BIN -c 'import secrets; print(secrets.token_urlsafe(32))')"
database_block="POSTGRES_DB=anglangl
POSTGRES_USER=cskang
POSTGRES_PASSWORD=
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432"
if [ "$USE_SQLITE_FALLBACK" = "1" ]; then
  database_block="USE_SQLITE=1
SQLITE_NAME=db.sqlite3"
fi

tmp_env="$(mktemp)"
cat > "$tmp_env" <<EOF
DJANGO_SECRET_KEY=${secret_key}
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=${PUBLIC_DOMAIN}
DJANGO_CSRF_TRUSTED_ORIGINS=https://${PUBLIC_DOMAIN}
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_LOG_DIR=/logs/anglangl
DJANGO_LOG_LEVEL=INFO
DJANGO_TIME_ZONE=Asia/Seoul
DJANGO_SECURE_SSL_REDIRECT=true
${database_block}
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
STATIC_URL=/static/
STATIC_ROOT=${ROOT_DIR}/staticfiles
MEDIA_URL=/media/
MEDIA_ROOT=${ROOT_DIR}/media
DJANGO_INTERNAL_API_TOKEN=${internal_api_token}
THEPEACH_AUTH_BASE_URL=${THEPEACH_ORIGIN_BASE_URL}
THEPEACH_LOGIN_BASE_URL=${THEPEACH_ORIGIN_BASE_URL}
THEPEACH_UPSTREAM_HOST_HEADER=${THEPEACH_PUBLIC_DOMAIN}
EOF

if sudo test -f "$ENV_FILE"; then
  sudo cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
fi

sudo mkdir -p /etc/anglangl
sudo install -m 640 -o root -g cskang "$tmp_env" "$ENV_FILE"
rm -f "$tmp_env"

echo "[2/4] Installing deployment files"
bash deploy/production/install_anglangl.sh

echo "[3/4] Validating deployment"
bash deploy/production/validate_anglangl.sh

echo "[4/4] Completed"
echo "Production URL: https://${PUBLIC_DOMAIN}"
