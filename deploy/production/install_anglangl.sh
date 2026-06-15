#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="/etc/anglangl/anglangl.env"
PYTHON_BIN="${PYTHON_BIN:-/home/cskang/miniconda3/envs/dj5/bin/python}"
PUBLIC_DOMAIN="${ANGLANGL_PUBLIC_DOMAIN:-anglangl.thesysm.com}"
USE_SQLITE_FALLBACK="${ANGLANGL_USE_SQLITE:-0}"
THEPEACH_PUBLIC_DOMAIN="${THEPEACH_PUBLIC_DOMAIN:-peach.thesysm.com}"
THEPEACH_ORIGIN_BASE_URL="${THEPEACH_ORIGIN_BASE_URL:-http://127.0.0.1}"

cd "$ROOT_DIR"

sudo mkdir -p /etc/anglangl /var/www/anglangl /logs/anglangl
sudo chown cskang:www-data /logs/anglangl
sudo chmod 775 /logs/anglangl

if [ ! -f "$ENV_FILE" ]; then
  secret_key="$($PYTHON_BIN - <<'PY'
import secrets

print(secrets.token_urlsafe(50))
PY
)"
  internal_api_token="$($PYTHON_BIN - <<'PY'
import secrets

print(secrets.token_urlsafe(32))
PY
)"
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
CELERY_QUEUES=default,youtube_download,clip_extract,clip_upload_process
CELERY_LOG_LEVEL=INFO
STATIC_URL=/static/
STATIC_ROOT=${ROOT_DIR}/staticfiles
MEDIA_URL=/media/
MEDIA_ROOT=${ROOT_DIR}/media
DJANGO_INTERNAL_API_TOKEN=${internal_api_token}
THEPEACH_AUTH_BASE_URL=${THEPEACH_ORIGIN_BASE_URL}
THEPEACH_LOGIN_BASE_URL=${THEPEACH_ORIGIN_BASE_URL}
THEPEACH_UPSTREAM_HOST_HEADER=${THEPEACH_PUBLIC_DOMAIN}
EOF
  sudo install -m 640 -o root -g cskang "$tmp_env" "$ENV_FILE"
  rm -f "$tmp_env"
  echo "Created $ENV_FILE"
fi

sudo install -m 644 -o root -g root deploy/production/gunicorn_anglangl.service /etc/systemd/system/gunicorn_anglangl.service
sudo install -m 644 -o root -g root deploy/production/celery_anglangl.service /etc/systemd/system/celery_anglangl.service
sudo install -m 644 -o root -g root deploy/production/nginx_anglangl.conf /etc/nginx/sites-available/anglangl
sudo ln -sfn /etc/nginx/sites-available/anglangl /etc/nginx/sites-enabled/anglangl

sudo ln -sfn "$ROOT_DIR/staticfiles" /var/www/anglangl/static
sudo ln -sfn "$ROOT_DIR/media" /var/www/anglangl/media

if ! sudo grep -q 'hostname: anglangl.thesysm.com' /etc/cloudflared/config.yml; then
  sudo cp /etc/cloudflared/config.yml "/etc/cloudflared/config.yml.bak.anglangl.$(date +%Y%m%d%H%M%S)"
  sudo python3 - <<'PY'
from pathlib import Path

path = Path("/etc/cloudflared/config.yml")
text = path.read_text()
needle = "  - service: http_status:404\n"
block = """  # anglangl
  - hostname: anglangl.thesysm.com
    service: http://localhost
    originRequest:
      unixSocketPath: /run/gunicorn_anglangl.sock
      httpHostHeader: anglangl.thesysm.com

"""
if "hostname: anglangl.thesysm.com" not in text:
    if needle in text:
        text = text.replace(needle, block + needle)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += block
path.write_text(text)
PY
fi

set -a
. "$ENV_FILE"
set +a
export DJANGO_SETTINGS_MODULE=config.settings.prod

if [ -S /tmp/gunicorn_anglangl.sock ]; then
  rm -f /tmp/gunicorn_anglangl.sock
fi

"$PYTHON_BIN" -m pip install -r requirements.txt
"$PYTHON_BIN" manage.py collectstatic --noinput
"$PYTHON_BIN" manage.py migrate --noinput
"$PYTHON_BIN" manage.py check --deploy

sudo systemctl daemon-reload
sudo systemctl disable --now gunicorn_anglangl.socket 2>/dev/null || true
sudo rm -f /etc/systemd/system/gunicorn_anglangl.socket /etc/systemd/system/sockets.target.wants/gunicorn_anglangl.socket
sudo rm -f /run/gunicorn_anglangl.sock
sudo systemctl enable gunicorn_anglangl.service
sudo systemctl restart gunicorn_anglangl.service
sudo systemctl enable celery_anglangl.service
sudo systemctl restart celery_anglangl.service
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl restart cloudflared

echo "anglangl production deployment files installed."
