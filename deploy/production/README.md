## anglangl Production Deployment Assets

These files are the source-controlled deployment assets for anglangl.

Target topology:

- Cloudflare Tunnel
- Nginx
- Gunicorn
- Django (`config.settings.prod`)

Installed targets:

- systemd socket: `/etc/systemd/system/gunicorn_anglangl.socket`
- systemd service: `/etc/systemd/system/gunicorn_anglangl.service`
- environment file: `/etc/anglangl/anglangl.env`
- nginx site: `/etc/nginx/sites-available/anglangl`
- nginx symlink: `/etc/nginx/sites-enabled/anglangl`
- cloudflared ingress fragment: merge into `/etc/cloudflared/config.yml`

Runtime paths:

- public socket path: `/run/gunicorn_anglangl.sock`
- actual socket path: `/run/anglangl/gunicorn.sock`
- static alias root: `/var/www/anglangl/static`
- media alias root: `/var/www/anglangl/media`
- application logs: `/logs/anglangl`

Notes:

- `manage.py` remains local-development friendly and defaults to `config.settings.local`.
- Gunicorn must set `DJANGO_SETTINGS_MODULE=config.settings.prod`.
- Secrets must live only in `/etc/anglangl/anglangl.env`.
- Gunicorn process must run as user `cskang` and group `www-data`.
- systemd creates `/run/anglangl/` as the writable runtime directory for the `cskang` process.
- `PermissionsStartOnly=true` lets root-owned pre-start steps prepare `/run/gunicorn_anglangl.sock` while the Gunicorn process itself still runs as `cskang`.
- `/run/gunicorn_anglangl.sock` is maintained as a symlink to `/run/anglangl/gunicorn.sock` for proxy compatibility.
- For a manual deployment run, use `deploy/production/run_anglangl_deploy.sh`.
