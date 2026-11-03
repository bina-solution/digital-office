#!/usr/bin/env python3
"""update-path-selfcheck — does `bbox update bina-ds` reach the self-update door, from ANYWHERE?

WHY THIS EXISTS. Recreating the container the agent harness runs in cuts every conversation working at
that moment; the one path that snapshots them and sends each its "carry on" message is
`apps/bina-ds/self-update.sh` (through `apps/bina-ds/hooks/self-update`). The compose guard in
scripts/lib.sh hands a recreate to that door only when the CALLER is inside the container being
replaced — `bbox_self_service` starts with `[ -f /.dockerenv ]` (lib.sh:697) — so on 2026-10-13 two
HOST-side `bbox update bina-ds` runs recreated the container directly and a session that was mid-turn
at 12:23:49Z never came back. scripts/app-update.sh now hands the replace to the door for any service
that ships one, and passes BBOX_UPDATE_NOW=1 so an EXPLICIT update is not held for the deployment's own
three-hour bound.

What this pins:
  1. the wiring: app-update.sh looks for `<root>/<id>/hooks/self-update` and calls it with
     BBOX_UPDATE_NOW=1 BEFORE falling back to its own `dc up -d --force-recreate`;
  2. that the door RUNS THIS CHECK from cmd_apply and refuses the apply when it fails — the state this
     defect shipped in was a contract written down with nothing running the check;
  3. the flag's behaviour, EXECUTED: BBOX_UPDATE_NOW grants a PATIENCE WINDOW (300 s), it does not
     apply at the first check — applying at the first check cut a live turn every time, measured
     2026-10-14 09:23 (session-07dd93c1, turn 1, `"kind":"interrupted"` at its 7th step) — while an
     operator's `BINA_DS_SELF_UPDATE_FORCE_AFTER=0` ("never wait for quiet") stays untouched and a
     window the operator narrowed is never widened;
  4. that the forced apply LOGS the conversations whose turns it is about to throw away, and that the
     resumed conversation is told where its own log is;
  5. the log clock: the door's own log() must stamp OFFICE time even when the caller is the host, where
     TZ is unset (UTC) — 2026-10-13 wrote `13:17:50` into a file whose neighbours said `16:17:23`.

Parts 2–5 are executed, not grepped: the code is lifted out of the script and run.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[3]
APP_UPDATE = REPO / "scripts" / "app-update.sh"
SELF_UPDATE = REPO / "apps" / "bina-ds" / "self-update.sh"
OFFICE_TZ = "Asia/Jerusalem"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def sh(script: str, env: dict | None = None) -> str:
    full = {**os.environ, "TZ": "UTC"}
    full.update(env or {})
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=full, timeout=60)
    return (r.stdout + r.stderr).strip()


def prologue(text: str) -> str:
    """The strict-mode line alone, and nothing else: a block lifted out of the door cannot run the way
    the door runs without its `set -euo pipefail`, and it cannot run WITH the file's other top-level
    statements, which read `.env`, `${REPO}` and the office's TZ."""
    line = next((ln for ln in text.splitlines() if ln.startswith("set -euo pipefail")), "")
    return line + "\n"


def brace_delta(line: str) -> int:
    """Net `{` minus `}` on one line, ignoring anything inside single or double quotes."""
    delta, quote, i = 0, None, 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#":
            break
        elif ch == "{":
            delta += 1
        elif ch == "}":
            delta -= 1
        i += 1
    return delta


def function_after(text: str, name: str) -> str:
    """One shell function, lifted whole: `name() {` through the `}` that closes it.

    `declare -f` cannot do this — sourcing the door runs its top level, which stops on
    `${BASH_SOURCE[0]}` with `set -u` — and counting braces naively cuts the function at the `}` of a
    one-line `else` branch. So the walk is quote-aware, which is exactly what the first version of this
    helper got wrong.
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if ln.startswith(f"{name}() {{") or ln.startswith(f"{name} () {{")), None)
    if start is None:
        return ""
    depth = 0
    for i in range(start, len(lines)):
        depth += brace_delta(lines[i])
        if depth == 0:
            return "\n".join(lines[start:i + 1])
    return ""


def block_after(text: str, first_line: str) -> str:
    """An `if … fi` construct, from its first line through the `fi` that closes IT.

    The match counts nesting, because a construct inside it closes on its own `fi`: the older flat form
    took `    if [ "${FORCE_AFTER}" -gt 0 ]` down to the *inner* `fi` of the loop's first branch, and a
    check for a line inside that block then read as missing.
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(first_line)), None)
    if start is None:
        return ""
    opens, closes = ("if", "for", "while", "until", "case"), ("fi", "done", "esac")
    depth = 0
    for i in range(start, len(lines)):
        head = lines[i].split("#", 1)[0].split()
        if not head:
            continue
        if head[0] in opens:
            depth += 1
        elif head[0] in closes:
            depth -= 1
            if depth == 0:
                return "\n".join(lines[start:i + 1])
    return ""


def main() -> int:
    results: list[tuple[str, bool, str]] = []
    au, su = read(APP_UPDATE), read(SELF_UPDATE)
    pro = prologue(su)

    # 1 — the wiring
    has_loop = re.search(r'for root in apps platform-base;.*hooks/self-update', au, re.S) is not None
    has_call = re.search(r'BBOX_UPDATE_NOW=1 bash "\$\{door\}" launch', au) is not None
    door_before_compose = (au.find('bash "${door}" launch') != -1
                           and au.find('bash "${door}" launch') < au.find('out="$(dc up -d --force-recreate "${svc}"'))
    results.append(("app-update.sh looks for <root>/<id>/hooks/self-update", has_loop, ""))
    results.append(("and calls it with BBOX_UPDATE_NOW=1", has_call, ""))
    results.append(("and only then falls back to its own dc up --force-recreate",
                    door_before_compose, ""))

    # 2 — AND THE DOOR RUNS THIS FILE BEFORE IT APPLIES, refusing on its answer. A check with no caller
    # is the state this defect shipped in. Both directions are run, not grepped.
    apply_block = function_after(su, "cmd_apply") or su
    selfcheck_block = function_after(su, "selfcheck")
    results.append(("cmd_apply calls the door's selfcheck before it applies",
                    "selfcheck || return 1" in apply_block, ""))
    for label, probe, want in [("and a FAILING self-check refuses the apply", "false", "rc=1"),
                               ("and a PASSING self-check lets it through", "true", "rc=0")]:
        # REPO is set because the door defines it at its top level and the guard's default names it;
        # the probe does not exist there, which is the point — SELFCHECK_CMD decides the answer.
        # `if selfcheck` and not `selfcheck; echo`: under the door's own `set -e` a bare failing call
        # would end the shell before the echo, and "no answer" is not "refused".
        script = (f'{pro}REPO=/nonexistent\n{selfcheck_block}\nLOG=/dev/null\nSELFCHECK_CMD={probe}\n'
                  'notify() { :; }\nlog() { :; }\n'
                  'if selfcheck; then echo "rc=0"; else echo "rc=1"; fi')
        got = sh(script).splitlines()[-1] if selfcheck_block else ""
        results.append((label, got == want, got))

    # 3 — the flag's behaviour, run. BBOX_UPDATE_NOW LIFTS THE DEPLOYMENT'S BOUND; it does not set the
    # bound to zero, and it does not widen a window an operator already narrowed.
    nowblock = block_after(su, 'if [ "${BBOX_UPDATE_NOW:-}" = 1 ]')
    for label, base, flag, env, want in [
        ("default + BBOX_UPDATE_NOW=1 → the patience window, not the first check", "10800", "1", "", "300"),
        ("default without the flag → the deployment's bound", "10800", "", "", "10800"),
        ("explicit FORCE_AFTER=0 (never) survives BBOX_UPDATE_NOW=1", "0", "1", "", "0"),
        ("an operator's bound is lowered by an EXPLICIT update", "600", "1", "", "300"),
        ("a patience already below the window is not raised",
         "10800", "1", "BINA_DS_SELF_UPDATE_PATIENCE=60", "60"),
        ("a patience already below the window is not raised (FORCE_AFTER above it)",
         "600", "1", "BINA_DS_SELF_UPDATE_PATIENCE=120", "120"),
    ]:
        script = "; ".join(x for x in (f"FORCE_AFTER={base}", f"BBOX_UPDATE_NOW={flag}", env) if x)
        got = sh(f'{script}; export BBOX_UPDATE_NOW\n{nowblock}\necho "$FORCE_AFTER"')
        results.append((f"BBOX_UPDATE_NOW: {label}", got == want, f"FORCE_AFTER={got} (wanted {want})"))
    # The patience window is a name, not a number, so it stays one decision in one place.
    results.append(("the patience window has a named default (BINA_DS_SELF_UPDATE_PATIENCE)",
                    'EXPLICIT_PATIENCE="${BINA_DS_SELF_UPDATE_PATIENCE:-300}"' in su, ""))
    # 3b — the cost is written down BEFORE it is paid: the apply line names the conversations whose
    # turns the restart is about to throw away, so the door's own file answers "what did that restart
    # cut?" without anyone reading session logs after the fact.
    cut_block = block_after(su, '    if [ "${FORCE_AFTER}" -gt 0 ]')
    results.append(("the forced apply LOGS the turns it is about to cut",
                    'CUT the turns running now' in cut_block and "live_sessions" in cut_block, ""))
    # 3c — and the resumed conversation is told HOW to find out what it had already done.
    results.append(("the resume message names the conversation's own log",
                    "session.v3.jsonl.zstd" in su and "zstd -dc" in su, ""))

    # 4 — the log clock, run: the same log() the door uses, called with a UTC caller
    logline = next((ln for ln in su.splitlines() if ln.startswith("log() {")), "")
    sets_tz = ('TZ="${LOG_TZ}" date' in logline
               and re.search(r'^LOG_TZ="\$\{LOG_TZ:-.*read_env TZ.*\}"', su, re.M) is not None
               and 'Asia/Jerusalem' in su)
    results.append(("the script picks the office's zone (from .env, default Asia/Jerusalem)", sets_tz, ""))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="bina-ds-log-selfcheck-"))
    stamped = sh(f'LOG_DIR="{tmp}"; LOG="$LOG_DIR/self-update.log"\n{logline}\nlog "probe"',
                 env={"LOG_TZ": OFFICE_TZ})
    want = subprocess.run(["date", "+%F %T"], capture_output=True, text=True,   # no `-d`: BSD date has none
                          env={**os.environ, "TZ": OFFICE_TZ}).stdout.strip()
    lines = [ln for ln in stamped.splitlines() if ln.strip()]
    got = " ".join(lines[-1].split()[:2]) if lines else ""
    # The same zone, read a moment later: equal to the SECOND failed whenever the two reads straddled one
    # (G72 under load, DGO-1040). A zone mistake is an hour or more, so a few seconds tell them apart.
    try:
        import datetime as _dt
        skew = abs((_dt.datetime.strptime(want, "%Y-%m-%d %H:%M:%S")
                    - _dt.datetime.strptime(got, "%Y-%m-%d %H:%M:%S")).total_seconds())
    except ValueError:
        skew = None
    results.append((f"the door's log stamps OFFICE time for a UTC caller ({got} vs {want})",
                    skew is not None and skew <= 5, stamped))

    bad = [n for n, ok, _ in results if not ok]
    for name, ok, detail in results:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if bad:
        print(f"SELFCHECK FAIL — {len(bad)} of {len(results)}: " + "; ".join(bad))
        return 1
    print(f"SELFCHECK PASS — an update reaches the self-update door from the host too "
          f"({len(results)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
