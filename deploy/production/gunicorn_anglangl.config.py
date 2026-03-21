import multiprocessing

bind = "unix:/run/anglangl/gunicorn.sock"
backlog = 2048

workers = min(4, max(2, multiprocessing.cpu_count()))
worker_class = "gthread"
threads = 2
worker_connections = 1000
timeout = 300
graceful_timeout = 30
keepalive = 2

max_requests = 1000
max_requests_jitter = 100

accesslog = "/logs/anglangl/gunicorn_access.log"
errorlog = "/logs/anglangl/gunicorn_error.log"
loglevel = "info"

proc_name = "anglangl"
daemon = False
preload_app = False
