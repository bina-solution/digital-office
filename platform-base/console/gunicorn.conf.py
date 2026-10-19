"""Gunicorn config for the console (the unified business-system shell).

Mirrors apps/indox/app/gunicorn.conf.py's rationale: ONE worker + threads, not multiple sync
workers. `python app.py` (Flask's built-in dev server, single-threaded) reverse-proxies EVERY
embedded app under /a/<name>/... — every asset and every API call for every app queued through
that one thread, so N concurrent requests cost close to the sum of their times rather than the
max. gthread fixes that within a single process: the console keeps a couple of small in-memory
caches (_OV_CACHE in app.py) that are harmless to duplicate per-worker, but there is no reason to
pay for multiple processes when the work here is I/O-bound (proxying HTTP to other containers) —
threads release the GIL for the `requests` calls that dominate this app's request time, and a
single worker keeps memory flat under the compose `deploy.resources.limits` (0.5 CPU / 256M).

threads=16, higher than indox's 8: the console fans out to far more concurrent upstream calls per
page (every embedded app's assets/APIs proxy through here at once), so it needs more headroom for
requests that are blocked on a slow upstream, not on CPU.

threads=48 since desktop mode (static/desktop.js): several apps stay on screen at once, each polling
or streaming through here, and 16 was measured to run out (2026-09-25: /healthz unanswered for ~7
minutes, the container marked unhealthy, traefik dropping the console). Streams are also bounded in
app.py (_bounded_stream) so none holds a thread for long.
"""

import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
backlog = int(os.getenv("GUNICORN_BACKLOG", "2048"))

workers = int(os.getenv("GUNICORN_WORKERS", "1"))
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "gthread")
threads = int(os.getenv("GUNICORN_THREADS", "48"))
worker_connections = 1000

# _proxy() uses timeout=40 for ordinary proxied calls, and app_proxy()'s streaming path uses
# timeout=(5, None) (connect 5s, NO read timeout) for text/event-stream — an SSE connection can
# sit open indefinitely. gunicorn's own `timeout` kills a worker that stops heartbeating the
# arbiter; with gthread that heartbeat is independent of any single request thread being blocked
# on a long read, but it is kept well above the 40s ordinary-proxy timeout anyway so a slow-but-
# finite upstream call is never the thing that trips it.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
keepalive = 5

# The console holds no per-request state that a worker recycle would lose (unlike indox's
# in-memory test runs) — safe to leave recycling off by default, same reasoning as indox.
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "0"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "0"))

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()

proc_name = "console"

preload_app = False
worker_tmp_dir = "/dev/shm"

graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
