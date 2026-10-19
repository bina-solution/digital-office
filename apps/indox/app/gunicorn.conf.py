"""Gunicorn config for the incoming-documents service."""

import os

bind = "0.0.0.0:8080"
backlog = int(os.getenv("GUNICORN_BACKLOG", "2048"))

# ONE worker + threads (not multiple sync workers): the BFF holds authoritative
# in-memory state — live test-run progress (_TEST_RUNS) and the run background
# threads — which a second worker process could not see (POST creates a run in
# worker A, the poll GET lands on worker B → 404). gthread keeps full concurrency
# for the SSE tail + slow proxied calls (sync/status, n8n lane webhooks) within
# the single process. Mirrors the morning BFF's 1-worker/gthread rationale.
workers = int(os.getenv("GUNICORN_WORKERS", "1"))
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "gthread")
threads = int(os.getenv("GUNICORN_THREADS", "8"))
worker_connections = 1000
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
keepalive = 5

# Worker recycling. The extraction runner keeps run/result state IN-MEMORY in the worker,
# so a mid-run recycle silently drops the in-flight run ("interrupted"). Default to 0
# (disabled) — the single BFF worker is long-lived and its footprint is small; set
# GUNICORN_MAX_REQUESTS>0 only if a leak needs periodic bouncing.
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "0"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "0"))

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()

proc_name = "incoming-documents"

preload_app = False
worker_tmp_dir = "/dev/shm"

graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "60"))
