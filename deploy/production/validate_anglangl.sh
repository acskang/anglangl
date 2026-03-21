#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/etc/anglangl/anglangl.env"
PYTHON_BIN="${PYTHON_BIN:-/home/cskang/miniconda3/envs/dj5/bin/python}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a
export DJANGO_SETTINGS_MODULE=config.settings.prod

"$PYTHON_BIN" manage.py check --deploy
curl --silent --show-error --fail --unix-socket /run/gunicorn_anglangl.sock -H 'Host: anglangl.thesysm.com' -H 'X-Forwarded-Proto: https' http://localhost/api/v1/health/
sudo systemctl status gunicorn_anglangl.service --no-pager --lines=0
sudo systemctl status nginx --no-pager --lines=0
sudo systemctl status cloudflared --no-pager --lines=0
