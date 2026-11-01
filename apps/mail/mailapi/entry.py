"""Entry module: the WSGI app (gunicorn runs `entry:app`).

It used to pick a backend module here, from GMAIL_IMAP_MODE, at process start — a build-time switch
for a runtime fact. The backend is now chosen per request from the selected connection
(service.py -> adapters.resolve_active), so this is a one-line re-export and GMAIL_IMAP_MODE means
only "what to use when nothing is selected". The HTTP contract is unchanged either way — workflows
and callers never change.
"""
from service import app  # noqa: F401

# Send a real IMAP LOGOUT for every open account when this worker stops (container stop / redeploy /
# gunicorn graceful shutdown). Gunicorn's gthread worker exits the process on SIGTERM, which runs
# atexit handlers, so this is the reliable teardown point. Without it Gmail keeps each abandoned
# server-side session for ~30 min against the ~15/account cap — the pile-up that made a fresh
# container fail to log in even though it holds a single socket.
import atexit
import adapters
atexit.register(adapters.close_all)

# The organiser defaults (tag rules) are mail-owned now: seed them from the
# shipped fixture on a fresh volume (create-only, never overwrites).
import organizer_seed
app.logger.info(organizer_seed.seed_if_missing())
