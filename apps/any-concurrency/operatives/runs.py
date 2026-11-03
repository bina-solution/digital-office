#!/usr/bin/env python3
"""n8n's executions of a window (GET /api/executions?hours=N), as the lines an agent can say: how many
ran and how each ended, the workflows that failed most, and what is still running and for how long —
or, with `--lane`, whether the collector reads n8n at all (GET /api/sources).

The runs recipe pipes into it — `./bbox any-concurrency executions <hours> | python3
apps/any-concurrency/operatives/runs.py <hours>`, or the same API through `./bbox remote <office>
<alias> …`, whose first line (`HTTP <status>  GET <url>`) it skips and whose office it names. The
answer is one record per execution (hundreds in an hour on a busy office): read whole, the counts an
agent needs are nowhere in it. The window counts runs that STARTED in it (app.py's query is on
`startedAt`), so a run stuck since before it is not there: the first line says the window, and a
stuck-run question asks for a day. An answer that is not a list of executions is printed as it came
and exits 1, so an n8n that did not answer is never "nothing ran".
"""
import collections
import json
import re
import sys
import time


def flat(v):
    return re.sub(r"\s+", " ", str(v or "")).replace("|", "¦").strip()[:120]


def minutes(ms):
    try:
        return int((time.time() * 1000 - float(ms)) / 60000)
    except (TypeError, ValueError):
        return None


def read(text):
    """(office, head, body): the `HTTP …` line of `bbox remote` taken off; head kept for a failure."""
    if not text.startswith("HTTP "):
        return "", "", text
    head, _, body = text.partition("\n")
    m = re.search(r"//[a-z0-9-]+\.([a-z0-9-]+)[:/]", head)
    return (m.group(1) if m else ""), head, body


def failure(head, body):
    print("\n".join(x for x in (head, (body or "(no answer)")[:600]) if x))
    return 1


def lane(text):
    office, head, body = read(text)
    who = f"{office}: " if office else ""
    try:
        n8n = json.loads(body)["n8n"]
        if re.match(r"HTTP [45]", head) or not isinstance(n8n, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        return failure(head, body)
    if n8n.get("ok"):
        print(f"{who}the n8n lane reads n8n's database: an empty window is a quiet one")
        return 0
    why = f" — {flat(n8n.get('error'))}" if n8n.get("error") else ""
    print(f"{who}the n8n lane is NOT reading{why}: the runs were not measured")
    return 1


def main(argv):
    text = sys.stdin.read()
    if argv[:1] == ["--lane"]:
        return lane(text)
    hours = argv[0] if argv and re.fullmatch(r"[0-9.]{1,6}", argv[0]) else None
    office, head, body = read(text)
    if re.match(r"HTTP [45]", head):
        return failure(head, body)
    try:
        rows = json.loads(body)
        if not isinstance(rows, list):
            raise ValueError
        by = collections.Counter(str(r["status"]) for r in rows)
    except (ValueError, KeyError, TypeError):
        return failure(head, body)
    who = f"{office}: " if office else ""
    window = f"started in the last {hours} h" if hours else "started in the window"
    if not rows:
        # app.py answers [] too when it holds no connection to n8n's database
        print(f"{who}no execution {window} — or n8n's database is not connected: the n8n lane says which")
        return 0
    print(f"{who}{len(rows)} executions {window}: " + ", ".join(f"{n} {s}" for s, n in by.most_common()))
    failed = collections.Counter(flat(r.get("svc")) for r in rows if r["status"] in ("error", "crashed"))
    for name, n in failed.most_common(6):
        print(f"{who}failed | {name} | {n}")
    running = sorted((r for r in rows if r["status"] == "running"), key=lambda r: r.get("s") or 0)
    for r in running[:6]:
        age = minutes(r.get("s"))
        print(f"{who}running | {flat(r.get('svc'))} | {flat(r.get('label'))} | "
              + (f"for {age} min" if age is not None else "since an unknown time"))
    if len(running) > 6:
        print(f"{who}running | and {len(running) - 6} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
