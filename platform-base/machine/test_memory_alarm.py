#!/usr/bin/env python3
"""test_memory_alarm.py — a machine out of memory is SAID: once, after a minute, and closed on recovery (DGO-2111 root 25).

vps1 (11-19, «ping yes, TCP no»), the Dell's freezes and the Mac's engine ran out of memory with no notice anywhere.
The watch's decisions are pinned here without starving a machine: the readings are handed to mem_watch(), and the
notices service is a recorder in place of app._notify / app._get_json.

    python3 platform-base/machine/test_memory_alarm.py      (inside the machine image: it imports the app)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app  # noqa: E402

FAIL: list[str] = []
GB = 1 << 30


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


SENT: list[tuple[str, str, dict | None]] = []
OPEN: list[dict] = []
UP = {"ok": True}


def fake_notify(method, url, body=None):
    if not UP["ok"]:
        return False
    SENT.append((method, url, body))
    if method == "POST" and body is not None:
        OPEN.append({"id": len(OPEN) + 1, "source_id": body["source_id"], "is_read": False})
    elif url.endswith("/read"):
        n = int(url.rsplit("/", 2)[-2])
        for row in OPEN:
            if row["id"] == n:
                row["is_read"] = True
    return True


app._notify = fake_notify
app._get_json = lambda url: {"notifications": [dict(r) for r in OPEN]}


def reading(avail_pct, swap_used=0, swap_total=0, total=16 * GB):
    return {"total": total, "available": int(total * avail_pct / 100), "used": 0, "percent": 0,
            "swap_used": swap_used, "swap_total": swap_total}


def reset():
    SENT.clear()
    OPEN.clear()
    UP["ok"] = True
    app._mem_alarm_state.update({"over": False, "low_ticks": 0})


def posts():
    return [b for (m, u, b) in SENT if m == "POST" and b is not None]


def ticks(n, r):
    for _ in range(n):
        app.mem_watch(r)


# the pure sentence
check(app.mem_alarm(40, 6 * GB, 0, 0) is None, "40% free: no alarm")
w = app.mem_alarm(4, 650 << 20, 3 * GB, 4 * GB)
check(w and w["level"] == "warn" and w["id"] == "machine-memory", "4% free: a warning, id machine-memory")
check(w and "650 MB" in w["body"] and "3.0 מתוך 4.0 GB" in w["body"], "the warning names the MB left and the swap")
e = app.mem_alarm(0.5, 83 << 20, 5 * GB, 5 * GB)
check(e and e["level"] == "error" and "83 MB" in e["title"], "0.5% free (the Mac's 83 MB of 11-19): an error")
check("אין למכונה swap" in app.mem_alarm(1, 100 << 20, 0, 0)["body"], "no swap is said as such")

# a spike is not an alarm: five low ticks, then one well
reset()
ticks(5, reading(3))
app.mem_watch(reading(30))
ticks(5, reading(3))
check(posts() == [], "five low ticks, a good one, five more: nothing said (a spike)")

# a minute low: said ONCE
reset()
ticks(app.MEM_SUSTAIN_TICKS, reading(3, 3 * GB, 4 * GB))
check(len(posts()) == 1 and posts()[0]["level"] == "warn", "six low ticks in a row: one warning")
check(posts()[0]["source"] == "machine" and posts()[0]["link"] == "/#/m/machine", "it is the machine's, linked to its screen")
ticks(30, reading(1))
check(len(posts()) == 1, "thirty more low ticks, deeper: still one notice")

# hovering under the clear line keeps it open; above it closes it
app.mem_watch(reading(7))
check(OPEN[0]["is_read"] is False and app._mem_alarm_state["over"], "7% free (under the 10% clear line): still open")
app.mem_watch(reading(12))
check(OPEN[0]["is_read"] is True and not app._mem_alarm_state["over"], "12% free: the notice is closed")
check(len(posts()) == 1, "the recovery posts no new notice")

# a second episode after the recovery is said again
ticks(app.MEM_SUSTAIN_TICKS, reading(2.5))
check(len(posts()) == 2, "a second low minute after a recovery: a second notice")

# the notices service down: not counted as said, tried again after another low minute
reset()
UP["ok"] = False
ticks(app.MEM_SUSTAIN_TICKS, reading(3))
check(not app._mem_alarm_state["over"] and app._mem_alarm_state["low_ticks"] == 0,
      "a failed post is not counted as said; the count starts again")
UP["ok"] = True
ticks(app.MEM_SUSTAIN_TICKS - 1, reading(3))
check(posts() == [], "it does not retry on every tick")
app.mem_watch(reading(3))
check(len(posts()) == 1, "it says it after another minute low, once the service answers")

# an unreadable meminfo is no alarm
reset()
ticks(10, {"total": 0, "available": 0, "used": 0, "percent": 0, "swap_used": 0, "swap_total": 0})
check(posts() == [] and app._mem_alarm_state["low_ticks"] == 0, "total 0 (unreadable): nothing")

print(f"\n{'FAILED ' + str(len(FAIL)) if FAIL else 'all passed'}")
sys.exit(1 if FAIL else 0)
