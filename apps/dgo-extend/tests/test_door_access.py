#!/usr/bin/env python3
"""test_door_access — the door's access log is read from `since`, never whole (`app._door_access`).

The security app asks `GET /api/link/access?since=<cursor>` every 10 s with a 5 s timeout. The route used
to parse every line of the log and of its rotated copy (up to 20 MB each) on every call and keep every
record after `since` before the slice. On the HP (2026-11-10) that read outlasted the timeout, the
cursor never moved, the container sat at its CPU and memory limits, and its link catalog missed the 8 s
its peers wait: every peer read the HP as «answers: down» over a live tunnel.

Asserted here, on the function the route calls:
  1. the same answer as the old full read, for every `since` (none, before the logs, inside the rotated
     file, at the seam, on an exact record time, inside the current file, after the end) and limit;
  2. a line that is not a record (torn, not JSON, not an object, no `ts`) is stepped over, as before,
     including where the search lands on it;
  3. records a few milliseconds out of order (two threads closing at once) are all returned;
  4. the cost follows what is returned: a cursor near the end of a 20 000-record log parses a few
     hundred lines, not 20 000, and a lagging cursor keeps `limit` records, not the backlog;
  5. the route's answer keeps its shape (items, more, source, present).
Run: python3 apps/dgo-extend/tests/test_door_access.py   (app.py loaded as test_app_input loads it)
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("test_app_input", HERE / "test_app_input.py")
tai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tai)
app = tai.load()

FAIL: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


def old_reader(paths, since: float, limit: int):
    """The route as it was before 2026-11-10: the reference answer. Verbatim but for one line: a JSON line
    that is not an object made the old route raise (a 500 for the whole read); it is stepped over here,
    as the new reader steps over it."""
    items: list = []
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    if float(rec.get("ts") or 0) > since:
                        items.append(rec)
        except OSError:
            continue
    items.sort(key=lambda r: r.get("ts") or 0)
    return items[:limit], len(items) > limit


def rec(ts: float, n: int, ms=12, end: float | None = None, old: bool = False) -> str:
    """One door line. `end` = the wall clock at close (the door writes it since DGO-1769); `old` = a line
    written before that, with no `end`."""
    r = {"ts": round(ts, 3), "office": "macbook", "app": "plane", "method": "GET", "path": f"/api/x/{n}",
         "status": 200, "bytes_out": 100 + n, "ms": ms, "user": "שלמה"}
    if not old:
        r["end"] = round(end if end is not None else ts + (ms if isinstance(ms, (int, float)) else 0) / 1000, 3)
    return json.dumps(r, ensure_ascii=False, separators=(",", ":"))


# The door writes a record when its connection CLOSES, with `ts` = when it started: the file is in order of
# ts + ms. Measured on the MacBook's own log (69 342 records): 4 600 out of `ts` order, 41 by more than a
# minute, the worst a `/plugins/events` stream 3.6 hours long. So: one request a second, a 3-hour stream and
# a 90-second one written where they closed, and two threads closing 3 ms apart written the other way round.
T0 = 1794300000.0
LONG = {9001: 3 * 3600 * 1000, 9002: 90_000}
events = [(T0 + i, i, 12) for i in range(800)] + [(T0 + 50, 9001, LONG[9001]), (T0 + 300, 9002, LONG[9002]),
                                                  (T0 + 600.004, 6001, 0), (T0 + 600.001, 6002, 0)]
# …and streams of 2–2.7 minutes all through both files, as the real log has them: where the search lands on one,
# its start says «long before», its end says where it is
events += [(T0 + 10.5 + k * 19, 7000 + k, 120_000 + k * 1000) for k in range(40)]
# …and requests of 5–50 s (an upload, a slow page) everywhere: they straddle every cut, which is what the
# minute of slack past the cut is for
events += [(T0 + 3.25 + k * 11, 5000 + k, 5_000 + (k * 7919) % 45_000) for k in range(70)]
events.sort(key=lambda e: e[0] + e[2] / 1000)
a, b = events.index((T0 + 600.001, 6002, 0)), events.index((T0 + 600.004, 6001, 0))
events[a], events[b] = events[b], events[a]            # the race: the later end written first
tmp = Path(tempfile.mkdtemp(prefix="dgo-door-access-"))
rotated, current = tmp / "door-access.jsonl.1", tmp / "door-access.jsonl"
lines_1, lines_c = [], []
for ts, n, ms in events:
    (lines_1 if ts + ms / 1000 < T0 + 400 else lines_c).append(rec(ts, n, ms))
    if n == 120:
        lines_1.append('{"ts": 1794300120.5, "torn')     # a torn write
    if n == 200:
        lines_1.append("not json at all")
        lines_1.append("[1, 2, 3]")                      # JSON, not an object
        lines_1.append('{"office": "no time"}')          # no ts: 0, never after a real cursor
rotated.write_text("\n".join(lines_1) + "\n", encoding="utf-8")
current.write_text("\n".join(lines_c) + "\n", encoding="utf-8")
PATHS = (rotated, current)
check(json.loads(lines_c[-1])["path"] == "/api/x/9001", "the 3-hour stream is the last line written")

# 1–3. the same answer as the old full read; where `limit` cuts, the only records it may leave out are
# connections that were still open a minute past the batch (`_door_access`'s docstring)
sinces = [0, T0 - 5000, T0 - 1, T0, T0 + 0.5, T0 + 49.5, T0 + 119.9, T0 + 120, T0 + 200, T0 + 250.25,
          T0 + 299.5, T0 + 399, T0 + 399.5, T0 + 400, T0 + 599.999, T0 + 600, T0 + 600.002, T0 + 700,
          T0 + 799, T0 + 800, T0 + 99999]
def agrees(paths, since: float, limit: int) -> bool:
    got = app._door_access(paths, since, limit)
    want = old_reader(paths, since, limit)
    if not want[1]:
        return got == want
    qualifying = old_reader(paths, since, 10 ** 9)[0]
    left = [r for r in want[0] if r not in got[0]]
    newest = max(r["ts"] for r in got[0])
    # left out only what was still OPEN a slack past the batch's newest start — not merely long (second reader)
    return bool(got[1] and len(got[0]) == limit and got[0] == sorted(got[0], key=lambda r: r["ts"])
                and all(r in qualifying and r["ts"] > since for r in got[0])
                and all(app._door_end(r) > newest + app._DOOR_SEEK_SLACK_S for r in left))


bad = []
for since in sinces:
    for limit in (1, 2, 7, 150, 401, 2000, 10000):
        if not agrees(PATHS, since, limit):
            got, want = app._door_access(PATHS, since, limit), old_reader(PATHS, since, limit)
            bad.append(f"since={since - T0:+.3f} limit={limit}: {len(got[0])}/{got[1]} vs {len(want[0])}/{want[1]}")
for line in bad:
    check(False, line)
check(not bad, f"{len(sinces)} cursors x 7 limits: uncut, the same records, order and `more` as the old full "
               "read; cut, at most the long-open connections left out")
sweep = [T0 - 3 + 7.3 * k for k in range(112)]
missed = [s - T0 for s in sweep if app._door_access(PATHS, s, 10000) != old_reader(PATHS, s, 10000)]
check(not missed, f"a cursor every 7.3 s across both files, uncut: exactly the old answer ({len(missed)} differ"
                  + (f", first at {missed[0]:+.1f} s)" if missed else ")"))
# The search must go by END time: a stream that started 500 s before its neighbours closed between them.
# Moved through every place of a small log, the search's first look lands on it in one of them; a search by
# start would read «long before», step past it, and lose the records written just before it.
lost = []
for j in range(1, 30):
    one = tmp / f"stream-at-{j}.jsonl"
    rows = [rec(T0 + i, i, 0) for i in range(31)]
    rows[j] = rec(T0 + j - 500, 8000 + j, 500_000)         # closed at T0+j, where it is written
    one.write_text("\n".join(rows) + "\n", encoding="utf-8")
    if app._door_access((tmp / "none.1", one), T0 + j - 1.5, 10000) != old_reader((one,), T0 + j - 1.5, 10000):
        lost.append(j)
check(not lost, f"a stream written among short requests, at each of 29 places: nothing lost (lost at {lost})")
# The second reader's case (DGO-1769): a client that sends its head slowly (600 s) and closes 0.1 s after,
# on lines written before the door wrote `end` — its `ts + ms` says 701.6. The cut must still hand over the
# 1.5-second request written after it.
slow = tmp / "slow-head.jsonl"
slow.write_text("\n".join([rec(100, 1, 0, old=True), rec(101, 2, 0, old=True),
                           rec(101.5, 3, 600_100, old=True), rec(100.5, 4, 1500, old=True)]) + "\n", encoding="utf-8")
check(app._door_access((slow,), 50, 2) == old_reader((slow,), 50, 2),
      "a slow head on an old line does not push a short request past the cut")
# A 61-second upload that closed inside the minute past the cut is long, but not open past it: it comes back
# (second reader: a reader that drops every long record at a cut passed the looser check).
upload = tmp / "upload.jsonl"
rows = [(T0 + i, i, 5) for i in range(101, 400)] + [(T0 + 200, 9100, 61_000)]
rows.sort(key=lambda e: e[0] + e[2] / 1000)
upload.write_text("\n".join(rec(*e) for e in rows) + "\n", encoding="utf-8")
got = app._door_access((upload,), T0 + 50, 150)
check("/api/x/9100" in {r["path"] for r in got[0]} and got == old_reader((upload,), T0 + 50, 150),
      "a 61 s upload that closed within the minute past the cut is returned")
# A connection open across a clock step (a laptop waking): its start is 4000 s before its neighbours, and the
# door's `end` is where it was written.
stepped = []
for k in range(1, 59, 3):
    one = tmp / f"step-at-{k}.jsonl"
    rows = [rec(T0 + i, i, 0) for i in range(60)]
    rows.insert(k, rec(T0 - 4000, 8500 + k, 55_000, end=T0 + k - 0.5))
    one.write_text("\n".join(rows) + "\n", encoding="utf-8")
    if app._door_access((one,), T0 + k - 2.5, 10000) != old_reader((one,), T0 + k - 2.5, 10000):
        stepped.append(k)
check(not stepped, f"a connection open across a clock step, at 20 places: nothing lost (lost at {stepped})")
# A bad `ms` is still a record; a NaN time is never after a cursor, as before.
odd = tmp / "odd.jsonl"
odd.write_text("\n".join([rec(T0 + 1, 1), rec(T0 + 2, 2, "x", old=True), '{"ts": NaN, "path": "/nan"}',
                          rec(T0 + 3, 3)]) + "\n", encoding="utf-8")
check(all(app._door_access((odd,), s, 10) == old_reader((odd,), s, 10) for s in (0, T0, T0 + 1.5)),
      "a line whose `ms` is not a number is kept, and a NaN time is skipped, as the old read did")
uncut = app._door_access(PATHS, T0 + 40, 10000)[0]
check({"/api/x/9001", "/api/x/9002"} <= {r["path"] for r in uncut},
      "a cursor before the streams started finds both, though they were written last")
check({r["path"] for r in app._door_access(PATHS, T0 + 599.5, 10)[0]} >= {"/api/x/6001", "/api/x/6002"},
      "the two records written 3 ms out of order are both returned")

# a file that is only junk, an empty file, a missing file
junk = tmp / "junk.jsonl"
junk.write_text("garbage\n{\"torn\n", encoding="utf-8")
empty = tmp / "empty.jsonl"
empty.write_text("", encoding="utf-8")
for name, paths in (("junk", (junk, current)), ("empty", (empty, current)), ("missing", (tmp / "gone", current))):
    ok = all(agrees(paths, s, lim) for s in (0, T0 + 450, T0 + 900) for lim in (50, 10000))
    check(ok, f"a {name} rotated file reads as before")

# 4. the cost follows what is returned
big = tmp / "big.jsonl"
with open(big, "w", encoding="utf-8") as fh:
    for i in range(20000):
        fh.write(rec(T0 + i, i) + "\n")
calls = {"n": 0}
real_loads = json.loads


def counting(s, *a, **k):
    calls["n"] += 1
    return real_loads(s, *a, **k)


json.loads = counting
try:
    items, more = app._door_access((tmp / "none.1", big), T0 + 19990, 2000)
    near_end = calls["n"]
    calls["n"] = 0
    lag_items, lag_more = app._door_access((tmp / "none.1", big), T0 + 100, 2000)
    lagging = calls["n"]
finally:
    json.loads = real_loads
check(len(items) == 9 and not more, "a cursor 10 s before the end returns the 9 newer records")
check(near_end < 200, f"…and parses {near_end} lines of 20000 (search + one minute of slack)")
check(len(lag_items) == 2000 and lag_more and lag_items[0]["ts"] == round(T0 + 101, 3),
      "a lagging cursor gets the next 2000 records and `more`, oldest first")
check(lagging < 2000 + 200, f"…parsing {lagging} lines, not the 19 900 after it")

# 5. the route keeps its shape
saved = app.DOOR_ACCESS_LOG
app.DOOR_ACCESS_LOG = current
try:
    out = app.api_link_access(since=T0 + 790, limit=2000)
finally:
    app.DOOR_ACCESS_LOG = saved
check(set(out) == {"items", "more", "source", "present"} and len(out["items"]) == 9 and out["more"] is False
      and out["present"] is True and out["source"] == str(current),
      "the route answers items/more/source/present as before")

print(f"\n{'FAIL' if FAIL else 'PASS'} test_door_access ({len(FAIL)} failed)")
raise SystemExit(1 if FAIL else 0)
