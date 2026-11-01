#!/bin/sh
# project-pln — replace upstream's start.sh.
#
# Two things upstream does that this deployment cannot live with:
#   * validate_domain_name() only accepts a bare FQDN or an IP, so `plane.localhost:8080` — the
#     only spelling that works on the macOS edge, which listens on 8080 — is rejected and the
#     container exits 1 before anything starts.
#   * it rewrites WEB_URL and CORS_ALLOWED_ORIGINS from DOMAIN_NAME on every boot, so there is no
#     way to say "the public origin is behind a proxy at a different port".
# And one thing it does that we keep, differently: SECRET_KEY / LIVE_SERVER_SECRET_KEY are
# generated on first boot. Upstream regenerates them if the container's filesystem is fresh;
# regenerating them invalidates every session and every signed URL, so ours live on the data
# volume and are only ever created once.
set -e

SECRETS_FILE=/app/data/plane.env.secrets
PLANE_ENV=/app/plane.env

mkdir -p /app/data /app/logs/access /app/logs/error

if [ -f "$SECRETS_FILE" ]; then
	# shellcheck disable=SC1090
	. "$SECRETS_FILE"
fi

if [ -z "${SECRET_KEY:-}" ] || [ -z "${LIVE_SERVER_SECRET_KEY:-}" ]; then
	SECRET_KEY="${SECRET_KEY:-$(tr -dc 'a-zA-Z0-9' </dev/urandom | head -c 50 || true)}"
	LIVE_SERVER_SECRET_KEY="${LIVE_SERVER_SECRET_KEY:-$(tr -dc 'a-zA-Z0-9' </dev/urandom | head -c 50 || true)}"
	umask 077
	printf 'SECRET_KEY=%s\nLIVE_SERVER_SECRET_KEY=%s\n' "$SECRET_KEY" "$LIVE_SERVER_SECRET_KEY" >"$SECRETS_FILE"
fi

# The public origin. WEB_URL and CORS_ALLOWED_ORIGINS must name EXACTLY what the browser uses —
# scheme and port included — or logins redirect to the wrong host and the websocket/API calls are
# refused as cross-origin. Set by docker-compose.yml from PROJECT_PLN_BASE_URL/PROJECT_PLN_PROTOCOL.
: "${WEB_URL:?WEB_URL must be set by docker-compose.yml}"
: "${DATABASE_URL:?DATABASE_URL must be set by docker-compose.yml}"
: "${REDIS_URL:?REDIS_URL must be set by docker-compose.yml}"
# The broker is REDIS in this deployment (patches/redis-broker.py): requiring AMQP_URL here made the
# container die in a restart loop the moment `plane-mq` was removed — the entrypoint insisted on a
# variable the new shape deliberately does not set. A broker is still mandatory, because a Celery app
# with none is a worker that silently does nothing.
: "${CELERY_BROKER_URL:-${AMQP_URL:-$REDIS_URL}}" >/dev/null 2>&1 || \
  { echo "entrypoint: no broker — set CELERY_BROKER_URL or REDIS_URL" >&2; exit 1; }

cat >"$PLANE_ENV" <<EOF
APP_PROTOCOL=$APP_PROTOCOL
DOMAIN_NAME=$DOMAIN_NAME
APP_DOMAIN=$DOMAIN_NAME
SITE_ADDRESS=${SITE_ADDRESS:-:80}
WEB_URL=$WEB_URL
CORS_ALLOWED_ORIGINS=$CORS_ALLOWED_ORIGINS
DATABASE_URL=$DATABASE_URL
REDIS_URL=$REDIS_URL
CELERY_BROKER_URL=${CELERY_BROKER_URL:-${AMQP_URL:-$REDIS_URL}}
SECRET_KEY=$SECRET_KEY
LIVE_SERVER_SECRET_KEY=$LIVE_SERVER_SECRET_KEY
AWS_REGION=${AWS_REGION:-us-east-1}
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-access-key}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-secret-key}
AWS_S3_BUCKET_NAME=${AWS_S3_BUCKET_NAME:-uploads}
AWS_S3_ENDPOINT_URL=${AWS_S3_ENDPOINT_URL:-}
BUCKET_NAME=${AWS_S3_BUCKET_NAME:-uploads}
USE_MINIO=${USE_MINIO:-1}
MINIO_ENDPOINT_SSL=${MINIO_ENDPOINT_SSL:-0}
FILE_SIZE_LIMIT=${FILE_SIZE_LIMIT:-5242880}
GUNICORN_WORKERS=${GUNICORN_WORKERS:-1}
CELERY_WORKER_CONCURRENCY=${CELERY_WORKER_CONCURRENCY:-1}
ENABLE_EMAIL_PASSWORD=${ENABLE_EMAIL_PASSWORD:-1}
API_KEY_RATE_LIMIT=${API_KEY_RATE_LIMIT:-60/minute}
DEBUG=${DEBUG:-0}
LIVE_BASE_PATH=/live
EOF

# supervisord and its children inherit whatever this shell exports, and the upstream service
# scripts read plane.env through the environment (start.sh did `export $(...)`; sourcing with
# `set -a` is the same thing without the word-splitting on values that contain spaces).
set -a
# shellcheck disable=SC1090
. "$PLANE_ENV"
set +a

echo "project-pln: origin=$WEB_URL minio=${USE_MINIO} workers=${GUNICORN_WORKERS} celery=${CELERY_WORKER_CONCURRENCY}"
exec /usr/local/bin/supervisord -c /etc/supervisor/conf.d/supervisor.conf
