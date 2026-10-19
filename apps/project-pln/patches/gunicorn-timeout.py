"""gunicorn-timeout.py — give the API worker a timeout that survives a burst.

    RUN python3 /app/patches/gunicorn-timeout.py    (Dockerfile, build time)

WHY. `/app/backend/bin/docker-entrypoint-api.sh` execs gunicorn without `--timeout`, so the default 30
seconds applies and gunicorn SIGKILLs a worker that takes longer than that on one request — measured on
this deployment as `WORKER TIMEOUT … was sent SIGKILL` every 30–60 seconds while a plan applied its
items, i.e. a burst of PATCHes produced a burst of 502s and a worker that was continuously dying.
Plane's own writes (an import, a plan, a bulk edit) legitimately take longer than 30s; a worker that is
killed mid-write is a worse outcome than a request that takes two minutes.

`GUNICORN_WORKERS` is already read from the environment by that script, so the timeout follows the same
pattern: 120s, and a 30s graceful window so an in-flight write finishes instead of being cut off.
"""
import pathlib
import sys

SCRIPT = pathlib.Path("/app/backend/bin/docker-entrypoint-api.sh")
NEEDLE = "exec gunicorn "
INSERT = "--timeout ${GUNICORN_TIMEOUT:-120} --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-30} "


def main() -> int:
    if not SCRIPT.exists():
        print(f"gunicorn-timeout: {SCRIPT} is missing — the image layout changed, refusing to guess")
        return 1
    src = SCRIPT.read_text(encoding="utf-8")
    if "--timeout" in src:
        print("gunicorn-timeout: already applied")
        return 0
    if NEEDLE not in src:
        print("gunicorn-timeout: no `exec gunicorn` line in the entrypoint — refusing")
        return 1
    out = src.replace(NEEDLE, NEEDLE + INSERT, 1)
    SCRIPT.write_text(out, encoding="utf-8")
    print("gunicorn-timeout: --timeout 120 --graceful-timeout 30 added to the API worker")
    return 0


if __name__ == "__main__":
    sys.exit(main())
