# gunicorn — the ONE place the drive's server settings live. The image's CMD and app.json's broker
# entrypoint (which wraps the same command in the credential injector) both run
# `gunicorn -c gunicorn.conf.py app:app`; they used to spell the flags out separately and drifted —
# the image said threaded workers and the entrypoint that actually ran said 2 sync workers.
#
# THREADED (gthread): every op here waits on I/O — storage, the vault, Postgres — and a sync worker
# sits occupied for the whole of a streamed download or upload. With 2 sync workers a few concurrent
# streams starved every other request into a client timeout (2026-08-05). Threads share a worker's
# memory, so this buys concurrency without the memory of more workers. The timeout is the worker's
# heartbeat, not a request's length, so a long stream is not killed.
bind = "0.0.0.0:8975"
worker_class = "gthread"
workers = 2
threads = 8
timeout = 120
graceful_timeout = 30
keepalive = 5
worker_tmp_dir = "/dev/shm"     # the heartbeat file; a slow disk must not make a busy worker look dead
accesslog = "-"
# The SAME JSON line apitools emits: any-concurrency reads `duration_us` off it to draw a request.
access_log_format = ('{"timestamp":"%(t)s","client_ip":"%(h)s","method":"%(m)s","path":"%(U)s",'
                     '"query":"%(q)s","status":%(s)s,"response_bytes":%(B)s,"user_agent":"%(a)s",'
                     '"duration_us":%(D)s}')
