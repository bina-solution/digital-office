"""worker-scheduler.py — run Plane's scheduled jobs inside the one worker this office keeps.

    RUN python3 /app/patches/worker-scheduler.py    (Dockerfile, build time)

WHY. The office runs four of the AIO's eight programs, and `beat` — a third full Django process —
is one of the four it dropped to fit the engine's memory (supervisor.conf). What went with it was
not "nice to have": Plane has twelve scheduled jobs and none of them ran. Nothing was hard-deleted,
no project's auto-archive or auto-close was applied, and no log was pruned — `api_activity_logs`,
which stores the full response of every request made with an API key, reached 504 MB in the two and
a half days the office's own task CLI had been talking to it (hp-laptop, 2026-10-07), with nothing
that would ever make it smaller.

Celery can run the scheduler inside a worker (`-B`). It is the wrong shape for a fleet — every
worker would send every job — and exactly the right one here: this container has ONE worker, by
construction. No third process, and the jobs run.

The telemetry job is among the twelve and stays silent: `no-phone-home.py` gates the task itself on
PLANE_TELEMETRY, not on whether anything schedules it.

Asserts its anchor, like every patch here: upstream changing how the worker starts must fail the
build rather than quietly ship an image whose logs grow for ever.
"""
import pathlib
import sys

SCRIPT = pathlib.Path("/app/backend/bin/docker-entrypoint-worker.sh")
OLD = "celery -A plane worker -l info"
NEW = "celery -A plane worker -B -l info"


def main() -> int:
    if not SCRIPT.exists():
        print(f"worker-scheduler: {SCRIPT} is missing — the image layout changed, refusing to guess")
        return 1
    src = SCRIPT.read_text(encoding="utf-8")
    if NEW in src:
        print("worker-scheduler: already applied")
        return 0
    if src.count(OLD) != 1:
        print(f"worker-scheduler: expected exactly one `{OLD}` in the worker entrypoint, found "
              f"{src.count(OLD)} — refusing")
        return 1
    SCRIPT.write_text(src.replace(OLD, NEW), encoding="utf-8")
    print("worker-scheduler: the worker also runs the scheduler (-B); Plane's twelve periodic jobs run again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
