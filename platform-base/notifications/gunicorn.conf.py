# gunicorn config for notifications. ONE worker so exactly ONE poll loop runs (the
# GlitchTip poller is a background thread; multiple workers would poll+dedupe-race).
# Low-traffic UI → 1 worker + threads is ample. post_worker_init starts the poller
# inside the (single) worker, after fork, so its thread is live.
bind = "0.0.0.0:8977"
workers = 1
threads = 4
timeout = 120
accesslog = "-"


def post_worker_init(worker):
    from app import start_poller
    start_poller()
