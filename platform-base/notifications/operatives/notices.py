#!/usr/bin/env python3
"""The notice board's answer (GET /api/notifications), one line per notice: level | source | title |
last seen — errors first — and what the answer can and cannot say.

The notifications recipe pipes into it — `curl -s '…/api/notifications?unread=1&limit=10' | python3
platform-base/notifications/operatives/notices.py 10`, or the same path through `./bbox remote <office>
alerts …`, whose first line (`HTTP <status>  GET <url>`) it skips and whose office it names. The
argument is the limit the call asked for — here no line names it — so a full page says there may be
more on either path. A title
is text from another system (GlitchTip, a workflow): every field is flattened to one line with its
`|` made `¦`, so it cannot forge a line. `count` is how many rows came back, never how many are
unread. An answer that is not a notice list is printed as it came and exits 1, so a board that did not
answer is never reported as an empty one.
"""
import json
import re
import sys

ERRORS = {"error", "fatal", "critical"}


def flat(v):
    return re.sub(r"\s+", " ", str(v or "")).replace("|", "¦").strip()[:200]


def main(argv):
    text = sys.stdin.read()
    office = ""
    limit = int(argv[0]) if argv and argv[0].isdigit() else None
    if text.startswith("HTTP "):
        head, _, text = text.partition("\n")
        m = re.search(r"//[a-z0-9-]+\.([a-z0-9-]+)[:/]", head)
        office = m.group(1) if m else ""
        m = re.search(r"[?&]limit=(\d+)", head)
        limit = limit or (int(m.group(1)) if m else None)
    try:
        rows = json.loads(text)["notifications"]
        if not isinstance(rows, list):                  # {"notifications": null} is no board's answer
            raise TypeError
    except (ValueError, KeyError, TypeError):
        print((text or "(no answer)")[:600])
        return 1
    who = f"{office}: " if office else ""
    if not rows:
        print(f"{who}the board has no unread notices")
        return 0
    rows.sort(key=lambda r: str(r.get("last_seen") or ""), reverse=True)                # newest first…
    rows.sort(key=lambda r: str(r.get("level") or "").lower() not in ERRORS)             # …errors before the rest
    for r in rows:
        level = str(r.get("level") or "info").lower()
        level = "error" if level in ERRORS else level
        print(f"{who}{level} | {flat(r.get('source'))} | {flat(r.get('title'))} | {flat(r.get('last_seen'))}")
    if limit and len(rows) >= limit:
        print(f"{who}these are the {len(rows)} newest; there may be more on the alerts screen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
