FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir flask gunicorn psycopg2-binary requests sentry-sdk cryptography
COPY app.py connections_client.py extensions.py db.py profiles.py bootstrap.py ./
# app.json is the ONLY place engine profiles are declared, and bootstrap.py reads it at start — so
# the manifest ships INSIDE the image rather than being restated as an env var somebody has to keep
# in step with it.
COPY app.json ./app.json
COPY adapters ./adapters
COPY static ./static
EXPOSE 8975
# gthread, not sync: every op here is I/O-bound (proxying supabase-storage / Google Drive over the
# network), so a sync worker sits idle-but-occupied for the whole streamed download. 2026-08-05 live
# finding: with 2 sync workers, a steady stream of concurrent n8n sync downloads starved every OTHER
# request on the process (readyz/healthz/connections included) into a client-side timeout, which
# n8n reported as "connection aborted, perhaps the server is offline" — indistinguishable in the n8n
# UI from drive actually being down. Threads share a worker's memory footprint, so this buys real
# concurrency headroom without the linear memory cost of more sync workers.
#
# --access-logformat is the SAME JSON line apitools emits (apps/apitools/gunicorn.conf.py). Not a
# style choice: any-concurrency builds a timeline span from an access line by reading `duration_us`
# off it (_parse_custom_line), and gunicorn's default CLF carries no duration at all — so under the
# default format this service can be seen only as a container, never as the requests it served.
# NOTE: the RUNNING command usually comes from app.json `broker.entrypoint` (the inject.sh wrapper
# that mints credentials), which overrides this CMD — the flag is set in BOTH places and they must
# stay in step.
CMD ["gunicorn","-w","2","--threads","6","-k","gthread","-b","0.0.0.0:8975","--timeout","120","--access-logfile","-","--access-logformat","{\"timestamp\":\"%(t)s\",\"client_ip\":\"%(h)s\",\"method\":\"%(m)s\",\"path\":\"%(U)s\",\"query\":\"%(q)s\",\"status\":%(s)s,\"response_bytes\":%(B)s,\"user_agent\":\"%(a)s\",\"duration_us\":%(D)s}","app:app"]
