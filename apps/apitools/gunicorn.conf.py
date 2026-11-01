#!/usr/bin/env python3
"""Gunicorn configuration for production deployment"""

import http.server
import os
import multiprocessing
import threading


# ── Health sidecar ────────────────────────────────────────────────────────────
# Runs in the Gunicorn MASTER process (not in workers), so it is NEVER blocked
# by in-flight documentJsonQuery requests. Traefik and Docker health checks
# point to this port (8082) so a saturated worker pool never kills the backend.

_HEALTH_PORT = int(os.getenv("GUNICORN_HEALTH_PORT", "8082"))


def _start_health_sidecar(port: int) -> None:
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"status":"healthy","source":"sidecar"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # suppress noisy access logs
            pass

    try:
        srv = http.server.HTTPServer(("0.0.0.0", port), _Handler)
        srv.serve_forever()
    except Exception as exc:
        import sys
        print(f"[gunicorn-health-sidecar] error: {exc}", file=sys.stderr)

# Server socket
bind = "0.0.0.0:8080"
# Large kernel-side accept queue so requests are queued (not dropped/503'd)
# when all workers are busy. Override via GUNICORN_BACKLOG env.
backlog = int(os.getenv("GUNICORN_BACKLOG", "4096"))

# Worker processes
# Env pins an explicit count; otherwise derive from the cgroup CPU quota (docker
# `cpus:`), NOT the raw core count — cpu_count() sees the whole VM and oversizes
# small containers (16 sync workers once idled at 1.6 GiB doing nothing). 1.5x
# the allotted cores covers OCR slots + json-query slots in flight; capped at 8
# because each worker also carries resident tesseract models (RAM, not CPU).
# SINGLE SOURCE. This used to be a private _allotted_cpus() here — a byte-for-byte reimplementation
# of autoscale._cgroup_cpu_quota(): same cgroup v2 path, same v1 fallback, same cpu_count() default,
# in the same app, in two files that could drift apart silently. Consolidated 2026-08-06.
#
# autoscale.py is the FALLBACK owner of machine-derived sizing (see its module docstring); the
# platform profile always wins via GUNICORN_WORKERS below. Import rather than re-derive.
def _allotted_cpus() -> float:
    try:
        from src.utils import autoscale
        return autoscale.ALLOTTED_CPUS
    except Exception:
        # gunicorn.conf.py is read before the app package is importable in some contexts (and this
        # file must never fail to load — a broken config means the server does not start at all).
        # Degrade to raw cores rather than raising; the env pin below is the normal path anyway.
        return float(multiprocessing.cpu_count())


_env_workers = os.getenv("GUNICORN_WORKERS")
if _env_workers:
    workers = int(_env_workers)
else:
    # MEASURED 2026-08-06 (real /proc RSS, this host): a worker that has handled ONE
    # large-document OCR call does not shrink back down afterward (CPython's allocator
    # doesn't return that memory to the OS) — workers were observed at 1.2-2.35 GiB
    # resident, and 4 kernel OOM-kills (3 of them GLOBAL host OOM, not this cgroup) landed
    # on exactly those bloated workers. The CPU-only formula below was previously capped
    # at 8 anyway; a profile had pinned this to 12 for an 8-core host and it was carried
    # unchanged onto a 6-core/9.7GiB one. Memory, not just cores, now bounds it — see
    # autoscale.gunicorn_workers_default().
    try:
        from src.utils import autoscale
        workers = autoscale.gunicorn_workers_default()
    except Exception:
        workers = max(2, min(int(_allotted_cpus() * 1.5), 8))
worker_class = "sync"
worker_connections = 1000
# OCR + fuzzy matching can take ~100s on large docs; allow plenty of room.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "300"))
keepalive = 5

# Restart workers after serving this many requests to prevent memory leaks.
# WAS 1000 — far too high given the measurement above: a worker that balloons to 1-2+
# GiB handling one large OCR document then stays that size for up to 999 MORE requests
# before recycling returns the memory to the OS. Lowered so a bloated worker is recycled
# within minutes under real traffic, not potentially hours. The cost (a fresh worker
# re-pays Tesseract model load, ~100-150ms) is negligible next to an OOM kill.
#
# THIS SETTING USED TO BE LOAD-BEARING FOR SOMETHING ELSE ENTIRELY, AND NO LONGER IS.
# src/doc_data/db.py cached its Postgres connection in a module global and never reset
# it, so a connection broken by a tunnel drop stayed broken for the life of the worker.
# The estate recovered from the 2026-08-11 split only because THIS line recycles every
# worker after ~35-65 requests — recovery by accident, from a knob whose stated purpose is
# memory. db.py now reconnects explicitly (see _reset()/Cursor.run there), so raising this
# value is once again purely a memory trade-off and no longer silently extends a database
# outage from minutes to hours. Keep it low for the memory reason above; do not keep it
# low believing it is the reconnect mechanism.
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "50"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "15"))

# Logging - use JSON format for structured logging
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
loglevel = os.getenv("LOG_LEVEL", "info").lower()

# Custom access log format with timing in milliseconds
# %(D)s is request time in microseconds, we'll handle conversion in our logging
access_log_format = '{"timestamp":"%(t)s","client_ip":"%(h)s","method":"%(m)s","path":"%(U)s","query":"%(q)s","status":%(s)s,"response_bytes":%(B)s,"user_agent":"%(a)s","duration_us":%(D)s}'

# Process naming
proc_name = "apitools"

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Performance - DISABLED preload_app to fix worker respawn issues
preload_app = False
worker_tmp_dir = "/dev/shm"  # Use memory for worker tmp files

# Graceful shutdown
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "120"))


def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Gunicorn master process starting")
    t = threading.Thread(target=_start_health_sidecar, args=(_HEALTH_PORT,), daemon=True)
    t.start()
    server.log.info("Health sidecar started on :%s", _HEALTH_PORT)


def when_ready(server):
    """Called just after the server is started."""
    server.log.info("Gunicorn server is ready. Listening on: %s", server.address)


def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass


def post_fork(server, worker):
    """Called just after a worker has been forked."""
    server.log.info("Worker spawned (pid: %s)", worker.pid)


def worker_int(worker):
    """Called when a worker receives SIGINT or SIGQUIT."""
    worker.log.info("Worker received INT or QUIT signal (pid: %s)", worker.pid)


def worker_abort(worker):
    """Called when a worker receives SIGABRT."""
    worker.log.warning("Worker received SIGABRT signal (pid: %s)", worker.pid)


def worker_exit(server, worker):
    """Called just after a worker has been exited."""
    server.log.info("Worker exited (pid: %s)", worker.pid)


def child_exit(server, worker):
    """Called when a worker process is terminated."""
    server.log.info("Worker child process terminated (pid: %s)", worker.pid)


def pre_exec(server):
    """Called just before a new master process is forked."""
    server.log.info("Forked child, re-executing master process")
