"""cli.py — `./bbox ci-runner <verb>`: the app's own API on loopback, inside its container (hooks/<verb> runs it).

    status | jobs [n] | queue | pause | resume        [--json]
    door                     the job door's named verbs (what a linked office may ask this office to run)
    door <bbox verb…>        ask the door for one, as the app's own CLI: its log as it runs, its result as the exit

One line per thing for a person, one JSON object with --json. Exit codes as the office's standard says: 0 answered,
1 failed, 2 usage, 3 the app did not answer.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8988"
VERBS = {"status": ("GET", "/api/status"), "jobs": ("GET", "/api/jobs"), "queue": ("GET", "/api/queue"),
         "pause": ("POST", "/api/pause"), "resume": ("POST", "/api/resume")}
USAGE = "usage: ci-runner status | jobs [n] | queue | pause | resume | door [<bbox verb…>]  [--json]"
DOOR_DONE = ("done", "failed", "timeout", "cancelled")


def call(method: str, path: str) -> dict:
    req = urllib.request.Request(BASE + path, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except ValueError:
            return {"ok": False, "error": f"HTTP {e.code}"}
    except ValueError:                                  # a 200 that is not JSON: the server is not this app's
        return {"ok": False, "error": "the answer was not JSON"}


def show_job(rec: dict) -> str:
    return (f"{rec.get('at', '')}  {rec.get('kind', ''):8} {rec.get('workflow', '')} · {(rec.get('sha') or '')[:7]} · "
            f"{rec.get('event_name', '')} של {rec.get('actor', '')}  (המתין {rec.get('waited_s', 0)} ש׳)")


def human(verb: str, data) -> str:
    if verb == "status":
        now = data.get("now")
        labels = ", ".join(data["labels"]) if data.get("labels") else "לא ידוע (אין אסימון GitHub בכספת)"
        return "\n".join([f"המריץ: {data.get('agent')} (דופק אחרון {data.get('heartbeat') or '—'})",
                          f"התוויות שלו ב־GitHub: {labels}",
                          "רץ עכשיו: " + (show_job(now) if now else "אין")])
    if verb == "jobs":
        return "\n".join(show_job(r) for r in data) or "אין עבודות ברשומה עדיין"
    if verb == "queue":
        if not data.get("available"):
            return f"התור לא זמין: {data.get('why')}"
        return "\n".join(f"{r['queued_at']}  {r['workflow']} · {r['sha']} · {r['branch']} · {r['actor']}"
                         for r in data.get("runs") or []) or "התור ריק"
    return ("הושהה — נעצר בין עבודות, והבאות נשארות בתור" if data.get("paused") else "חזר לקבל עבודות") + \
        ("" if data.get("changed") else " (כבר היה כך)")


def door(words: list[str], as_json: bool) -> int:
    """`door` lists the named verbs; `door <words…>` asks for one and follows its log to the end."""
    if not words:
        got = call("GET", "/api/door/names")
        if as_json or not got.get("ok"):
            print(json.dumps(got, ensure_ascii=False) if as_json else got.get("error", "failed"),
                  file=sys.stdout if as_json else sys.stderr)
            return 0 if got.get("ok") else 1
        for name, job in sorted((got.get("data") or {}).items()):
            print(f"{name} ({job.get('class')}, עד {job.get('timeout_s')} ש׳): {job.get('what', '')}")
            for tpl in job.get("verbs") or []:
                print("   " + " ".join(tpl))
        return 0
    req = urllib.request.Request(BASE + "/api/door/jobs", method="POST",
                                 data=json.dumps({"name": "bbox", "args": {"verb": words}}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            got = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            got = json.load(e)
        except ValueError:
            got = {"ok": False, "error": f"HTTP {e.code}"}
    if not got.get("ok"):
        print(got.get("error") or "failed", file=sys.stderr)
        return 1
    jid, offset, end = got["data"]["id"], 0, time.time() + 700
    while time.time() < end:
        with urllib.request.urlopen(f"{BASE}/api/door/jobs/{jid}/log?offset={offset}", timeout=20) as r:
            page, state, code = r.read(), r.headers.get("X-Door-State", ""), r.headers.get("X-Door-Exit", "")
            offset = int(r.headers.get("X-Door-Next") or offset + len(page))
        if page and not as_json:
            sys.stdout.write(page.decode("utf-8", "replace"))
            sys.stdout.flush()
        if state in DOOR_DONE and not page:
            if as_json:
                print(json.dumps({"ok": state == "done", "id": jid, "state": state, "exit": code}))
            elif state != "done":
                print(f"door: the job ended {state} (exit {code or '—'})", file=sys.stderr)
            return 0 if state == "done" else 1
        time.sleep(0 if page else 1)
    print(f"door: job {jid} had not ended when the CLI stopped waiting — it goes on; its log stays at "
          f"/api/door/jobs/{jid}/log", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--json"]
    as_json = len(args) != len(argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if args else 2
    verb, rest = args[0], args[1:]
    if verb == "door":
        try:
            return door(rest, as_json)
        except OSError as e:
            print(f"ci-runner did not answer: {e}", file=sys.stderr)
            return 3
    if verb not in VERBS or (rest and verb != "jobs") or len(rest) > 1 or (rest and not rest[0].isdigit()):
        print(USAGE, file=sys.stderr)
        return 2
    method, path = VERBS[verb]
    if verb == "jobs" and rest:
        path += f"?n={rest[0]}"
    try:
        got = call(method, path)
    except OSError as e:
        print(f"ci-runner did not answer: {e}", file=sys.stderr)
        return 3
    if as_json:
        print(json.dumps(got, ensure_ascii=False))
    elif got.get("ok"):
        print(human(verb, got.get("data")))
    else:
        print(got.get("error") or "failed", file=sys.stderr)
    return 0 if got.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
