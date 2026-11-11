#!/usr/bin/env python3
"""bbox via — run a bbox command on a LINKED office, in that office's own checkout (DGO-1092).

    bbox via <office> [--timeout S] [--put FILE]… <bbox args…>   e.g.  bbox via vps1 project-pln tasks show DGO-12

`--put FILE` carries one of THIS machine's files to the other office first (to a temporary directory
there, removed after the command, under its own name), and every argument that names FILE — or `@FILE`,
the shape of `--comment @<file>` — is rewritten to that path: a plan file written here and not
committed, the files a work item is given (`tasks attach`), the text of a long comment.

Why: offices are paired two by two, so an office reaches only the offices it has a live pair with.
A laptop away from home has no pair that answers to the offices at home, but the herd's hub
(apps/computers/herd.yaml `hub:`, the public office every office pairs with) still does. Through the
hub, a verb runs as if it were typed there: its Plane, its links, its compute. The owner, 2026-11-01:
«no matter where I am, everything keeps working and I have control over the full herd».

How, first: THE JOB DOOR (DGO-1797, package 10). If the office runs `ci-runner` and takes jobs from this office
(its CI_RUNNER_ACCEPT_FROM), a verb on its list (`./bbox ci-runner door` there) is asked as a NAMED job —
`POST /api/door/jobs` through the link, which signs the request as this office — and its log is printed when it
ends; the exit is the job's. No shell is opened there. Any other answer (no door, not this office's to ask, not a
door verb) and the call goes on as before. `--put` files, and BBOX_VIA_DOOR=off, skip the door.
How, else: `bbox remote <office> computers /api/computers/computer_local-local/exec`. That is the office's
own Computers app, reached through the link with the link's own credential (scripts/remote.py), and it
runs a shell on that office's machine. The checkout is the one the office's own containers were started
from (their compose project's working directory), so nothing here names a path per office. Every
argument is shell-quoted on the way, so what arrives there is exactly what was typed here.
An office with neither (no host shell — the HP has no sshd — and no door that runs the verb) is said in those words.
Exit status: the remote command's own, 2 when the office could not be asked at all.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TIMEOUT = 300          # the Computers app allows up to 600 s (apps/computers/app.py MAX_TIMEOUT)
# The whole command is ONE argument twice on the way — the exec's JSON handed to remote.py here, and the
# command handed to ssh by the office's Computers app there — and Linux caps one argument at 128 KiB
# (MAX_ARG_STRLEN). So the limit is on the command, carried files included (gzip'd and base64'd): a plan
# or the office's reports file (YAML packs 4-5x) fits with room to grow; a photo for `tasks attach`
# mostly does not, and is refused here, in words, rather than cut there.
MAX_WIRE = 120 << 10

# Where the office's checkout is: the working directory of the compose project its own `computers`
# service was started from. One docker query on that machine; no path is written down per office.
WHERE = ("W=$(docker inspect --format '{{index .Config.Labels \"com.docker.compose.project.working_dir\"}}' "
         "$(docker ps -q --filter label=com.docker.compose.service=computers | head -1) 2>/dev/null); "
         "[ -n \"$W\" ] && [ -x \"$W/bbox\" ] || { echo 'via: no bbox checkout found on this office' >&2; exit 97; }; "
         "cd \"$W\" && ")


DOOR_APP = "ci-runner"          # the app whose job door runs a named job (apps/ci-runner/door.py)
DOOR_DONE = ("done", "failed", "timeout", "cancelled")


def _remote_json(office: str, alias: str, path: str, method: str = "GET", body=None, timeout: int = 30):
    """One call through the link with scripts/remote.py --json → (HTTP status, body text); (0, why) when the office
    could not be asked at all."""
    call = [sys.executable, os.path.join(REPO, "scripts", "remote.py"), office, alias, path, "--json",
            "--timeout", str(timeout), "-X", method]
    if body is not None:
        call += ["-H", "Content-Type: application/json", "--data-raw=" + json.dumps(body, ensure_ascii=False)]
    try:
        p = subprocess.run(call, capture_output=True, text=True, timeout=timeout + 30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 0, f"could not ask ({type(e).__name__})"
    start = p.stdout.find("{")
    try:
        out = json.loads(p.stdout[start:], strict=False) if start >= 0 else {}
    except ValueError:
        out = {}
    if not out:
        return 0, (p.stdout + p.stderr).strip()[-200:]
    return int(out.get("status") or 0), str(out.get("body") or "")


def _door_published(office: str) -> bool:
    """Whether `office` publishes its job door to this one at all: the compiler's record of that remote app
    (.generated/registry/remote.<office>.ci-runner.json, what scripts/remote.py itself resolves from). Read before
    any call, so a `bbox via` to an office with no door costs nothing (the second reader measured ~1 s a call)."""
    return os.path.isfile(os.path.join(REPO, ".generated", "registry", f"remote.{office}.{DOOR_APP}.json"))


def _door_verb(words: list) -> bool:
    """Whether `bbox <words>` is a job the door runs, by the door's OWN check (apps/ci-runner/door.py `validate`
    over its jobs.json — the one copy, loaded from this checkout): a verb off the list then never costs a link round
    trip just to be told 400. A door.py that cannot be LOADED here is asked anyway (its own answer decides); a
    jobs.json that is missing here means nothing goes to the door — the host shell, as before the door existed."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ci_runner_door", os.path.join(REPO, "apps", DOOR_APP, "door.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.validate({"name": "bbox", "args": {"verb": list(words)}})[0] is not None
    except Exception:                                     # noqa: BLE001 — an unreadable check never blocks the ask
        return True


def door(office: str, words: list, timeout: int) -> tuple[int | None, str]:
    """Ask `office`'s job door for `bbox <words>` → (the job's exit, "") when the door ran it, or (None, why) when the
    door is not the way — then the host shell is asked, and `why` is said if that fails too."""
    status, text = _remote_json(office, DOOR_APP, "/api/door/jobs", "POST", {"name": "bbox", "args": {"verb": words}})
    if status != 202:
        try:
            why = json.loads(text).get("error") or ""
        except ValueError:
            why = ""
        return None, (f"its job door answered {status}" + (f": {why[:160]}" if why else "")) if status else \
            "its job door could not be asked"
    try:
        jid = json.loads(text)["data"]["id"]
    except (ValueError, KeyError, TypeError):
        return None, "its job door answered without a job id"
    row, end = {}, time.monotonic() + timeout + 60
    while time.monotonic() < end:
        status, text = _remote_json(office, DOOR_APP, f"/api/door/jobs/{jid}")
        if status == 200:
            try:
                row = json.loads(text).get("data") or {}
            except ValueError:
                row = {}
            if row.get("state") in DOOR_DONE:
                break
        time.sleep(2)
    else:
        sys.stderr.write(f"via: job {jid} on {office}'s door had not ended after {timeout + 60} s — it goes on there\n")
        return 124, ""
    offset = 0
    while True:
        status, page = _remote_json(office, DOOR_APP, f"/api/door/jobs/{jid}/log?offset={offset}")
        if status != 200 or not page:
            break
        sys.stdout.write(page)
        offset += len(page.encode("utf-8"))
    state, code = row.get("state"), row.get("exit")
    if state == "done":
        return 0, ""
    if state == "timeout":
        sys.stderr.write(f"via: the job ran past its timeout on {office}'s door and was stopped there\n")
        return 124, ""
    return (code if isinstance(code, int) and code else 1), ""


def usage(code: int = 2) -> int:
    sys.stderr.write("usage: bbox via <office> [--timeout S] [--put FILE]… <bbox args…>\n")
    return code


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return usage(0 if argv else 2)
    office, rest = argv[0], argv[1:]
    timeout, puts = DEFAULT_TIMEOUT, []
    while rest[:1] in (["--timeout"], ["--put"]) and len(rest) > 1:
        if rest[0] == "--timeout":
            try:
                timeout = max(1, min(600, int(rest[1])))
            except ValueError:
                return usage()
        else:
            puts.append(rest[1])
        rest = rest[2:]
    if not rest:
        return usage()
    door_why = ""
    if (not puts and (os.environ.get("BBOX_VIA_DOOR") or "on").lower() != "off" and _door_published(office)
            and _door_verb(rest)):
        got, door_why = door(office, rest, timeout)
        if got is not None:
            return got
    # Each carried file: written there under its own name (an attachment is named after it), in a directory
    # of this run that only root can read (it may be a client's document) and that goes when the shell does
    # — a command stopped at its timeout included, which is why a signal is turned into an exit.
    run, staged, there = f"/tmp/bbox-via-{uuid.uuid4().hex[:8]}", [], {}
    for f in puts:
        if f in there:
            continue
        if not os.path.isfile(f):
            sys.stderr.write(f"via: --put {f}: not a file here\n")
            return 2
        data = base64.b64encode(gzip.compress(open(f, "rb").read())).decode()
        dst = f"{run}/{len(staged)}/{os.path.basename(f)}"
        staged.append(f"mkdir -p {shlex.quote(os.path.dirname(dst))} && "
                      f"printf %s {shlex.quote(data)} | base64 -d | gunzip > {shlex.quote(dst)}")
        there[f] = dst
    rest = [there[a] if a in there else "@" + there[a[1:]] if a[:1] == "@" and a[1:] in there else a
            for a in rest]
    command = WHERE + "".join(s + " && " for s in staged) + "BBOX_VIA=1 ./bbox " + shlex.join(rest)
    if there:
        command = (f"umask 077; trap 'rm -rf {run}' EXIT; trap 'exit 129' HUP INT TERM; " + command)
    body = json.dumps({"command": command, "timeout": timeout}, ensure_ascii=False)
    if len(body.encode()) > MAX_WIRE:
        sys.stderr.write(f"via: the command is {len(body.encode()) >> 10} KiB{' with its files' if there else ''}, "
                         f"more than the {MAX_WIRE >> 10} KiB one argument can carry through the link — "
                         "send it when the direct link is back\n")
        return 2
    call = [sys.executable, os.path.join(REPO, "scripts", "remote.py"), office, "computers",
            "/api/computers/computer_local-local/exec", "--timeout", str(timeout + 30),
            "-H", "Content-Type: application/json", "--data-raw=" + body]
    # An office whose apps are being recreated (a deploy) answers its link proxy's 502/503/504 AT ONCE:
    # the request never reached the app, so asking again cannot run anything twice. A late one may have
    # run the command already, and is reported, never repeated (measured 2026-11-01 12:34 on vps1: its
    # `computers` recreated, a ticket comment refused with 502 — and a minute later the same call ran).
    for attempt in range(3):
        began = time.monotonic()
        try:
            p = subprocess.run(call, capture_output=True, text=True)
        except OSError as e:
            sys.stderr.write(f"via: could not start the call to {office} ({e})\n")
            return 2
        raw = p.stdout
        refused = None if '"code"' in raw else re.search(r"HTTP 50[234]\b", raw + p.stderr)
        if not (refused and time.monotonic() - began < 10 and attempt < 2):
            break
        sys.stderr.write(f"via: {office} answered {refused.group(0)} at once (its apps restarting?) — asking again in 15 s\n")
        time.sleep(15)
    start = raw.find('{"')
    also = f" (and {door_why})" if door_why else ""
    if start < 0:
        sys.stderr.write(f"via: {office} could not be asked — {(raw + p.stderr).strip()[-400:]}{also}\n")
        return 2
    try:
        out = json.loads(raw[start:], strict=False)
    except ValueError:
        sys.stderr.write(f"via: {office} answered something that is not the exec's answer: {raw[start:start + 300]}\n")
        return 2
    if "code" not in out and not out.get("timed_out"):
        # the Computers app's own refusal (`{"error": …}`): it never ran the command
        sys.stderr.write(f"via: {office} did not run it — {out.get('error') or raw[start:start + 300]}\n")
        return 2
    sys.stdout.write(out.get("stdout") or "")
    if out.get("stderr"):
        sys.stderr.write(out["stderr"])
    if out.get("timed_out"):
        sys.stderr.write(f"via: the command ran past {timeout} s on {office} and was stopped there\n")
        return 124
    code = out.get("code")
    if code and not out.get("stdout") and not out.get("stderr"):
        # a shell that never started (ssh refused, the machine asleep) says why only in these words
        why = " — ".join(str(out[k]) for k in ("reason", "action") if out.get(k))
        sys.stderr.write(f"via: {office} answered exit {code} and printed nothing{' — ' + why if why else ''}\n")
        if door_why:
            sys.stderr.write(f"via: {office} has no host shell that answers, and no job door that runs this verb "
                             f"({door_why})\n")
    return code if isinstance(code, int) else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
