"""redis-broker.py — run Celery on the Redis this app already carries, instead of RabbitMQ.

    RUN python3 /app/patches/redis-broker.py     (Dockerfile, build time)

WHY IT IS A PATCH AND NOT A SETTING. Upstream `plane/settings/common.py` derives the Celery broker
from exactly one variable — `CELERY_BROKER_URL = os.environ.get("AMQP_URL")` — so "just set
CELERY_BROKER_URL in the environment" is overwritten by that assignment, and the app keeps talking to
RabbitMQ whether or not an AMQP_URL was given. (Measured on this deployment: with `plane-mq` gone and
no AMQP_URL, the worker came up against localhost:5672 and looped on connection refused.) Redis is a
documented Celery broker, and this app already carries `plane-redis` as cache/session/result store, so
the broker is the one dependency that can be removed without adding anything.

WHAT IT DOES, in one line at the END of the settings module: state the broker explicitly, preferring
anything the operator set, then the AMQP URL if one is configured, then REDIS_URL. Appending rather
than substituting keeps the patch independent of upstream's surrounding text — the assignment we care
about runs before ours — and the assertion below is what makes a silent no-op impossible.
"""

from __future__ import annotations

import pathlib
import sys

SETTINGS = pathlib.Path("/app/backend/plane/settings/common.py")

MARKER = "# --- bina: Celery broker on Redis (patches/redis-broker.py) ---"
BLOCK = f'''

{MARKER}
# RabbitMQ is not part of this deployment: `plane-mq` was removed and no AMQP_URL is set, so the
# broker is the Redis this app already runs. `CELERY_BROKER_URL` is preferred if an operator sets it;
# an AMQP_URL still wins over Redis, so re-adding RabbitMQ needs only that variable back.
CELERY_BROKER_URL = (
    os.environ.get("CELERY_BROKER_URL")
    or os.environ.get("AMQP_URL")
    or REDIS_URL
)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or REDIS_URL
'''


def main() -> int:
    if not SETTINGS.exists():
        print(f"redis-broker: {SETTINGS} is missing — the image layout changed, refusing to guess")
        return 1
    src = SETTINGS.read_text(encoding="utf-8")
    if MARKER in src:
        print("redis-broker: already applied")
        return 0
    # The anchor is the thing being fixed: if upstream stops deriving the broker from AMQP_URL, this
    # patch is no longer needed and should be deleted rather than blindly appended.
    if 'os.environ.get("AMQP_URL")' not in src:
        print("redis-broker: common.py no longer reads AMQP_URL — the patch is obsolete, remove it")
        return 1
    if "REDIS_URL" not in src:
        print("redis-broker: no REDIS_URL in common.py — cannot fall back to redis, refusing")
        return 1
    SETTINGS.write_text(src.rstrip("\n") + "\n" + BLOCK, encoding="utf-8")
    print("redis-broker: Celery now brokers on REDIS_URL unless CELERY_BROKER_URL/AMQP_URL say otherwise")
    return 0


if __name__ == "__main__":
    sys.exit(main())
