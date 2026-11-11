#!/usr/bin/env python3
"""outbox.py — the ticket writes that found no path to Plane, kept until one is back (DGO-1100, any-201).

`tasks start|done|comment|take|attach|label|unlabel|link|new|edit|rm` and `plan` are WRITES. When this office has no path
to its Plane — it does not run the app here and no linked office publishes it, or the door that does
is not answering, or the herd's hub is not answering either — a write used to fail and the words were
lost. They are kept here instead, in the order they were asked for, and sent by the first run that
HAS a path (hooks/tasks and hooks/plan flush before they do their own work), or on demand:

    ./bbox project-pln tasks flush

The store is this office's own: `<repo>/.state/outbox/project-pln/` (git-ignored; `PLN_OUTBOX_DIR`
moves it, which is how the test runs it in a scratch directory).
- `pending/<seq>/entry.json` — one write: its verb, its arguments, and the files it carried.
- `last-seen` — when this office last reached Plane, which is what an offline read answers with.

The order is the files' own: `<seq>` is zero-padded and claimed under a lock, so the queue replays
in the order it was written and two runs never claim the same number. An entry is removed only after
its command answered success, so nothing is lost; a command that failed stops the queue (order is
the contract), and the entry stays for the next attempt. The one exception is an `attach` that Plane
answered and refused part of FOR GOOD (exit ANSWERED_REFUSED: a file type it takes not): the rest
landed, a replay cannot change the answer, so it is said and leaves the queue. The one window that is not closed: a
request that Plane accepted and whose answer died on the way back still looks unsent here, and a
`comment` would be written twice. State changes (`start`, `done`, `take`) and `plan` are upserts and
say the same thing twice harmlessly.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEFAULT_DIR = os.environ.get("PLN_OUTBOX_DIR") or os.path.join(REPO, ".state", "outbox", "project-pln")
WRITE_VERBS = ("start", "done", "comment", "take", "attach", "label", "unlabel", "link", "new", "edit", "rm", "item",
               "plan")   # new/edit/rm/item: DGO-1252; unlabel was a write the list had missed
#: The exit of a write Plane ANSWERED and refused part of (tasks.py `attach`: a file it takes no such type of —
#: the others landed). Sent and said; never sent again. The same number is tasks.py's ANSWERED_REFUSED.
ANSWERED_REFUSED = 4


def log(msg: str) -> None:
    print(f"[project-pln] {msg}", flush=True)


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


@contextlib.contextmanager
def locked(d: str):
    """One writer at a time, across processes and across two `bbox` runs typed at once."""
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "lock"), "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def pending(d: str) -> list:
    p = os.path.join(d, "pending")
    if not os.path.isdir(p):
        return []
    return sorted(x for x in os.listdir(p) if os.path.isdir(os.path.join(p, x)))


def count(d: str) -> int:
    return len(pending(d))


def queue(d: str, verb: str, args: list, copies: list) -> int:
    """Keep one write: its verb, its arguments, and a copy of every file it carried (the plan file of
    `plan`, the documents of `attach`). Returns the number waiting — what the reply says."""
    with locked(d):
        p = os.path.join(d, "pending")
        seq = len(pending(d)) + 1
        entry = os.path.join(p, "%06d" % seq)
        while os.path.exists(entry):                 # the same sequence twice can only be a leftover
            seq += 1
            entry = os.path.join(p, "%06d" % seq)
        os.makedirs(os.path.join(entry, "files"))
        mapped, files = {}, {}
        for i, src in enumerate(copies):
            if not os.path.isfile(src):
                continue
            # by its OWN name, in a directory of its own (two files of one write may share a name): an attach
            # replayed from here lands on the item as the file the person named, not «0-<name>» — which is
            # also what lets the replay see the files that landed before the line went down (DGO-1628)
            os.makedirs(os.path.join(entry, "files", str(i)))
            dst = os.path.join(entry, "files", str(i), os.path.basename(src))
            shutil.copy2(src, dst)
            mapped[src] = dst
            files[src] = dst
        # the arguments travel as typed, with each carried file named by its copy — the same rewrite
        # `bbox via --put` does, and the reason `--comment @<file>` keeps its `@`
        new_args = [mapped[a] if a in mapped
                    else "@" + mapped[a[1:]] if a.startswith("@") and a[1:] in mapped else a
                    for a in args]
        with open(os.path.join(entry, "entry.json"), "w", encoding="utf-8") as fh:
            json.dump({"seq": seq, "created": now(), "verb": verb, "args": new_args, "files": files},
                      fh, ensure_ascii=False)
        return len(pending(d))


def bbox() -> str:
    return os.environ.get("PLN_BBOX") or os.path.join(REPO, "bbox")


def flush(d: str, quiet: bool = False) -> int:
    """Send what is waiting, oldest first, and stop at the first failure (order is the contract)."""
    if os.environ.get("PLN_OUTBOX_REPLAY"):
        # Inside a replay this queue is being sent already, by the flush that holds its lock, so a
        # second flush would wait for that lock forever. Measured 2026-11-05 on vps1: hooks/plan flushes
        # before its apply, also when it IS the replay; a queued plan hung there, and every later write
        # of the office waited behind the same lock (nine writers from five sessions, 75 minutes).
        return 0
    with locked(d):
        names = pending(d)
        if not names:
            if not quiet:
                log("התיבה ריקה — אין כתיבה שממתינה")
            return 0
        sent = 0
        for name in names:
            entry = os.path.join(d, "pending", name)
            try:
                with open(os.path.join(entry, "entry.json"), encoding="utf-8") as fh:
                    e = json.load(fh)
            except (OSError, ValueError):
                log("%s: קובץ פגום בתיבה — מדלג" % name)
                sent += 1
                shutil.rmtree(entry, ignore_errors=True)     # nothing recoverable in it
                continue
            verb = e.get("verb") or ""
            cmd = [bbox(), "project-pln", "plan" if verb == "plan" else "tasks"] + list(e.get("args") or [])
            log("בתור — נשלח עכשיו: %s" % " ".join(cmd[1:]))
            env = dict(os.environ)
            env["PLN_OUTBOX_REPLAY"] = "1"          # never queue again from inside a replay
            try:
                rc = subprocess.run(cmd, env=env).returncode
            except OSError as err:
                log("לא נשלח (%s) — נשאר בתור, %d ממתין" % (err, count(d)))
                return 3
            if rc == ANSWERED_REFUSED and verb == "attach":   # only attach says it; any other 4 keeps its entry
                # Plane answered and refused part of it (a file it takes no such type of): the rest landed, and
                # sending it again cannot change the answer. It is said and leaves the queue — kept, it would
                # stop every later write of this office behind it for good (DGO-1628's second reader).
                log("נשלח — Plane דחה חלק ממנו (נאמר למעלה), ולא יישלח שוב")
                shutil.rmtree(entry, ignore_errors=True)
                sent += 1
                continue
            if rc != 0:
                log("לא נשלח (exit %d) — נשאר בתור, %d ממתין" % (rc, count(d)))
                return 3
            shutil.rmtree(entry, ignore_errors=True)
            sent += 1
        log("נשלחו %d — התיבה ריקה" % sent)
        return 0


def seen(d: str) -> int:
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "last-seen"), "w", encoding="utf-8") as fh:
        fh.write(now() + "\n")
    return 0


def last_seen(d: str) -> str:
    try:
        with open(os.path.join(d, "last-seen"), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def main(argv: list) -> int:
    d = DEFAULT_DIR
    while argv[:1] in (["--dir"],):
        d = argv[1]
        argv = argv[2:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    verb, rest = argv[0], argv[1:]
    if verb == "queue":
        want, copies, args, i = "", [], [], 0
        while i < len(rest):
            a = rest[i]
            if a == "--verb":
                want = rest[i + 1]
                i += 2
                continue
            if a == "--copy":
                copies.append(rest[i + 1])
                i += 2
                continue
            if a == "--":
                args = rest[i + 1:]
                break
            i += 1
        if not want or want not in WRITE_VERBS or not args:
            sys.stderr.write("usage: outbox.py queue --verb <verb> [--copy FILE]… -- <args…>\n")
            return 2
        print(queue(d, want, args, copies))
        return 0
    if verb == "flush":
        return flush(d, quiet="--quiet" in rest)
    if verb == "count":
        print(count(d))
        return 0
    if verb == "seen":
        return seen(d)
    if verb == "lastseen":
        print(last_seen(d))
        return 0
    sys.stderr.write("unknown command %r\n" % verb)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
