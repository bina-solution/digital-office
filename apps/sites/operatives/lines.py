#!/usr/bin/env python3
"""The sites overview (GET /api/overview), as one line per website an agent can say: its state, its
uptime over 24 h, how long ago it was checked, and its open findings — and a line when the scheduler
that checks them is not running.

The sites recipe pipes into it — `curl -sS http://sites:8979/api/overview | python3
apps/sites/operatives/lines.py`, or the same API through `./bbox remote <office> <alias> …`, whose first
line (`HTTP <status>  GET <url>`) it skips and whose office it names. The overview carries times as
Unix seconds and no "now": the age is worked out here, not left to a model. An answer that is not an
overview is printed as it came and exits 1, so a sites app that did not answer is never "all up".
"""
import json
import re
import sys
import time

STALE_S = 600


def flat(v):
    return re.sub(r"\s+", " ", str(v or "")).replace("|", "¦").strip()[:160]


def checked(ts):
    try:
        s = int(time.time() - float(ts))
    except (TypeError, ValueError):
        return "never checked"
    if s < -120:                                          # the far office's clock is ahead of this one's
        return "checked at a time ahead of this office's clock"
    s = max(s, 0)
    said = f"checked {s // 60} min ago" if s < 7200 else f"checked {s // 3600} h ago"
    return said + (" (stale)" if s > STALE_S else "")


def line(s):
    if s.get("enabled") is False:
        state = "disabled"
    elif s.get("monitor") is False:
        state = "not monitored"
    elif not s.get("last_state"):
        state = "not checked yet"
    elif s["last_state"] == "down":
        state = f"DOWN — {flat(s.get('last_error'))}" if s.get("last_error") else "DOWN"
    else:
        state = flat(s["last_state"])
    parts = [flat(s.get("label") or s.get("id")), state]
    if state == flat(s.get("last_state")) or state.startswith("DOWN"):
        up = s.get("uptime") if isinstance(s.get("uptime"), dict) else {}
        parts.append(f"{up['uptime_pct']}% up over 24 h ({up.get('samples')} checks)"
                     if up.get("uptime_pct") is not None else "no checks in 24 h")
        parts.append(checked(s.get("last_checked")))
    f = s.get("findings") if isinstance(s.get("findings"), dict) else {}
    if f.get("error") or f.get("warn"):
        parts.append(f"open findings: {f.get('error', 0)} errors, {f.get('warn', 0)} warnings")
    if s.get("url"):
        parts.append(flat(s["url"]))
    return " | ".join(parts)


def main():
    text = sys.stdin.read()
    office, head = "", ""
    if text.startswith("HTTP "):
        head, _, text = text.partition("\n")
        if re.match(r"HTTP [45]", head):
            print(head)
            print(text[:600])
            return 1
        m = re.search(r"//[a-z0-9-]+\.([a-z0-9-]+)[:/]", head)
        office = m.group(1) if m else ""
    try:
        d = json.loads(text)
        sites = d["sites"]
        if not isinstance(sites, list):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        # the head too: a sign-in redirect (HTTP 302, no body) is said as one, not as no answer
        print("\n".join(x for x in (head, (text or "(no answer)")[:600]) if x))
        return 1
    who = f"{office}: " if office else ""
    sched = d.get("scheduler") if isinstance(d.get("scheduler"), dict) else {}
    if sched and not sched.get("started"):
        print(f"{who}the scheduler is not running: no site is being checked, and the states below are old")
    for err in (sched.get("errors") or [])[-3:]:          # the newest: scheduler.py appends
        print(f"{who}scheduler error: {flat(err)}")
    if not sites:
        print(f"{who}no websites registered")
    for s in sites:
        print(who + line(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
