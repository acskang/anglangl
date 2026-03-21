#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <start|stop|restart|status>" >&2
  exit 1
fi

sudo systemctl "$1" gunicorn_anglangl.service
