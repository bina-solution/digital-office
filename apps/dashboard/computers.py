#!/usr/bin/env python3
"""computers.py — the control centre's computers, a line each, for `./bbox dashboard computers` (DGO-1052).

Runs inside dashboard-feed (`python3 /app/computers.py [--json]`; this directory is its /app), where the collector
writes /data/state.json — a temp file and one rename (feed.py `write`), so it is never read half-written. It reads
that snapshot and nothing else, and probes nothing: the computers and the item totals the owner's first screen
shows (not the screen's power word or the owner's group). A state is the screen's dot:

  up    green  — linked, and its office's machine takes commands
  half  sky    — linked, but no command door from here (the reason is printed)
  down  plum   — the link does not answer (since when, when the link recorded the fall)
  away         — the link from here is down, and another office reaches it now
  none  hollow — declared in apps/computers/herd.yaml, not linked to this office

Exit 0 / 1 no snapshot yet, or not JSON / 2 usage.
"""
import json
import sys
import time

STATE = "/data/state.json"
STALE_S = 150          # the collector's own healthcheck (docker-compose.yml): older than this, it has stopped
USAGE = "computers [--json]"


def since(row):
    """The row's time as the screen shows it: `when_ts` (a down row's recorded fall) as "since …", else the
    collector's own word (`when`). An away row keeps `since_ts` (when the direct link fell) but feed.py drops its
    `when_ts` and says «עכשיו» — it is heard NOW, through another office — so that word is what is printed."""
    ts = row.get("when_ts")
    if isinstance(ts, (int, float)) and ts > 0:
        return "since " + time.strftime("%Y-%m-%d %H:%MZ", time.gmtime(ts))
    return str(row.get("when") or "")


def reason(row):
    """What the screen says about a row that is not green: the link's own error for down/away, the note for the
    rest (half: why there is no command door; none: not linked here)."""
    st = row.get("state")
    if st in ("down", "away"):
        return str(row.get("why") or "")
    if st in ("half", "none"):
        return str(row.get("note") or "")
    return ""


def lines(state, now):
    age = int(now - (state.get("at") or 0))
    out = [f"snapshot: {age}s old" + (f" — stale: the collector counts over {STALE_S}s as stopped"
                                      if age > STALE_S else "")]
    for c in state.get("computers") or []:
        words = [f"  {str(c.get('state') or '?'):<5}",
                 f"{c.get('name') or c.get('id') or '?'} ({c.get('office') or '?'})"]
        when = since(c)
        if when:
            words.append(when)
        why = reason(c)
        out.append(" ".join(words) + (f" — {why}" if why else ""))
    totals = state.get("totals") or {}
    if totals:
        out.append(f"items: {totals.get('completed')} done of {totals.get('all')}, {totals.get('started')} started, "
                   f"{totals.get('owner')} the owner's")
    for name, err in (state.get("errors") or {}).items():
        out.append(f"  ! {name}: {err}")
    return out


def main(argv, path=STATE, now=None):
    args = list(argv[1:])
    unknown = [a for a in args if a != "--json"]
    if unknown:
        print(f"dashboard computers: unknown argument '{unknown[0]}' ({USAGE})", file=sys.stderr)
        return 2
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        state = json.loads(raw)
    except OSError:
        print("the collector has written no snapshot yet: it writes one after its first whole pass", file=sys.stderr)
        return 1
    except ValueError:
        print(f"{path} is not JSON", file=sys.stderr)
        return 1
    if not isinstance(state, dict):
        print(f"{path} is not the collector's snapshot", file=sys.stderr)
        return 1
    if "--json" in args:
        print(raw.rstrip("\n"))
        return 0
    for line in lines(state, time.time() if now is None else now):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
