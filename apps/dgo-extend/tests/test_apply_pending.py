#!/usr/bin/env python3
"""test_apply_pending — a new remote app found while the apply window holds is applied after it, not dropped (DGO-1314).

    python3 apps/dgo-extend/tests/test_apply_pending.py      # or: python3 -m pytest apps/dgo-extend/tests/test_apply_pending.py

A linked office publishes an app; the projection writes it into the state and asks the control plane for ONE
apply, at most once per APPLY_MIN_SECONDS (600 s), so a flapping link cannot restart the edge in a loop. A
SECOND new app five minutes later found the window shut — and was simply dropped: the next pass saw the block
unchanged (it was already written), so nothing ever applied it, and its tile waited for an unrelated change or
a hand-run converge. Now what the window holds back waits in link-apply.json and the first pass after the
window applies it; a failed apply waits the same way. On the code before DGO-1314 the third step fails.

Hermetic: the control plane is a stand-in that records what it was asked, the clock is set by the test.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/dgo-extend"))

import projection  # noqa: E402

FAILS: list[str] = []
APPLY = ("POST", f"/api/apps/{projection.SELF_APP}/apply", {})


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n        {detail}"))
    if not ok:
        FAILS.append(name)


class Plane:
    def __init__(self, ok: bool = True):
        self.asked, self.ok = [], ok

    def _http(self, method, url, body=None, timeout=None):
        self.asked.append((method, url.replace(projection.CONTROL_URL, ""), body))
        return {"ok": self.ok} if self.ok else {"error": "the compile failed"}


def block(*aliases: str) -> list[dict]:
    return [{"office": "macbook", "address": "10.79.1.2", "link_port": 9003,
             "apps": [{"alias": a, "app": a, "port": 80} for a in aliases]}]


def waiting(base: str) -> list[str]:
    """What the stamp says waits — read off the file, so the code before DGO-1314 (which kept nothing) answers []."""
    import json
    try:
        p = json.loads((Path(base) / projection.APPLY_STAMP).read_text(encoding="utf-8")).get("pending")
    except (OSError, ValueError, AttributeError):
        return []
    return sorted(p) if isinstance(p, list) else []


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


def main() -> int:
    real_time = projection.time.time
    clock = Clock(1_800_000_000.0)
    projection.time.time = clock
    try:
        with tempfile.TemporaryDirectory() as base:
            # t0: the first new app is applied at once
            p = Plane()
            r = projection.apply_new_remote_apps(p, {}, [], block("files"), base)
            check("the first new app is applied", r.get("ran") is True and p.asked == [APPLY], f"{r} {p.asked}")

            # t0 + 5 min: a second new app — the window holds the apply back, and the app is KEPT
            clock.t += 300
            p = Plane()
            r = projection.apply_new_remote_apps(p, {}, block("files"), block("files", "plane"), base)
            check("five minutes later the window holds the second one back", r.get("ran") is False and p.asked == [],
                  f"{r} {p.asked}")
            check("…and it waits in the stamp", waiting(base) == ["macbook/plane"], repr(waiting(base)))

            # t0 + 8 min: a pass with nothing new — still inside the window, still waiting
            clock.t += 180
            p = Plane()
            r = projection.apply_new_remote_apps(p, {}, block("files", "plane"), block("files", "plane"), base)
            check("inside the window nothing runs, and the app still waits",
                  r.get("ran") is False and p.asked == [] and waiting(base) == ["macbook/plane"], f"{r} {p.asked}")

            # t0 + 10 min 1 s: the block is unchanged by now, and the waiting app is applied
            clock.t += 121
            p = Plane()
            r = projection.apply_new_remote_apps(p, {}, block("files", "plane"), block("files", "plane"), base)
            check("the first pass after the window applies the app that waited",
                  r.get("ran") is True and r.get("new") == ["macbook/plane"] and p.asked == [APPLY], f"{r} {p.asked}")
            check("…and nothing waits after it", waiting(base) == [], repr(waiting(base)))

            # a failed apply waits too, and an unpairing's failed apply (which names no app) keeps what waited
            clock.t += 601
            p = Plane(ok=False)
            r = projection.apply_new_remote_apps(p, {}, block("files", "plane"), block("files", "plane", "mail"), base)
            check("a failed apply leaves its app waiting", r.get("ok") is False and waiting(base) == ["macbook/mail"],
                  repr(waiting(base)))
            clock.t += 601
            projection.apply_now(Plane(ok=False), [], base)
            check("…and a failed unpairing apply does not drop it", waiting(base) == ["macbook/mail"], repr(waiting(base)))
            clock.t += 601
            p = Plane()
            r = projection.apply_new_remote_apps(p, {}, block("files", "plane", "mail"), block("files", "plane", "mail"),
                                                 base)
            check("…until a pass after the window applies it", r.get("ran") is True and r.get("ok") is True
                  and waiting(base) == [], f"{r} {waiting(base)}")

            # an apply that keeps failing is not asked again for ever (the second reader): after three failures in a
            # row a pass with nothing new is held, and the next new app is applied again
            for _ in range(3):
                clock.t += 601
                projection.apply_new_remote_apps(Plane(ok=False), {}, block("files", "plane", "mail"),
                                                 block("files", "plane", "mail", "chat"), base)
            clock.t += 601
            p = Plane()
            r = projection.apply_new_remote_apps(p, {}, block("files", "plane", "mail", "chat"),
                                                 block("files", "plane", "mail", "chat"), base)
            check("after three failed applies in a row, a pass with nothing new is held",
                  r.get("ran") is False and p.asked == [] and "held" in r.get("reason", "")
                  and waiting(base) == ["macbook/chat"], f"{r} {p.asked}")
            clock.t += 601
            p = Plane()
            r = projection.apply_new_remote_apps(p, {}, block("files", "plane", "mail", "chat"),
                                                 block("files", "plane", "mail", "chat", "meet"), base)
            check("…and the next new app is applied again, with what waited", r.get("ran") is True
                  and r.get("new") == ["macbook/chat", "macbook/meet"] and p.asked == [APPLY], f"{r} {p.asked}")

            # unchanged behaviour: an app that went away never applies, and nothing at all does nothing
            clock.t += 601
            p = Plane()
            r = projection.apply_new_remote_apps(p, {}, block("files", "plane"), block("files"), base)
            check("an app that went away does not apply (as before)", r.get("ran") is False and p.asked == [], repr(r))
    finally:
        projection.time.time = real_time
    print(f"\n{'all passed' if not FAILS else f'{len(FAILS)} failed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
