FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Every .py in this directory, rather than a hand-maintained list. The list was a trap: adding
# mailsetup.py and rebuilding produced a GREEN build and an image without the module, and the
# failure only surfaces at request time as an ImportError inside a running container. A COPY that
# silently omits new source is worse than one that breaks loudly. `.dockerignore` beside this file
# keeps the glob from also shipping test_*.py and __pycache__ (N12: test modules leave the image).
COPY *.py .
# No `COPY static` any more: the service's own browser client was deleted (RELEASE-DECISIONS N12 —
# one mail client, mailview). mailapi is an API: n8n, mailview and the console call it by name.
# the mail-owned label organiser's rule fixture — seeded into the defaults singleton on a fresh
# volume (organizer_seed.py). Lives HERE now, not in indox (mail-organizer-refactor §8).
COPY fixtures ./fixtures
ENV PORT=8970
EXPOSE 8970
# single worker: imapclient connection is stateful + guarded by an in-process lock.
# --access-logfile - logs every request to stdout (request visibility for n8n integration debugging).
#
# --access-logformat is the SAME JSON line apitools emits (apps/apitools/gunicorn.conf.py). Not a
# style choice: any-concurrency builds a timeline span from an access line by reading `duration_us`
# off it (_parse_custom_line), and gunicorn's default CLF carries no duration at all — so under the
# default format this service can be seen only as a container, never as the requests it served.
# One format across apitools/mailapi/drive means one parser serves all three; changing it here
# silently drops this lane off the timeline.
# Worker/thread sizing above is deliberately untouched — the single worker and its 12 threads are a
# standing decision about the stateful per-mailbox IMAP connection, not something the log format
# has any bearing on.
CMD ["gunicorn","-w","1","-k","gthread","--threads","12","-b","0.0.0.0:8970","--timeout","120","--access-logfile","-","--access-logformat","{\"timestamp\":\"%(t)s\",\"client_ip\":\"%(h)s\",\"method\":\"%(m)s\",\"path\":\"%(U)s\",\"query\":\"%(q)s\",\"status\":%(s)s,\"response_bytes\":%(B)s,\"user_agent\":\"%(a)s\",\"duration_us\":%(D)s}","entry:app"]
