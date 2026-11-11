"""bbox agent --office <office> … where this office has no link to <office>: the same command, run on that
office's own machine through this office's Computers app (DGO-1684).

`--office` speaks agent.v1 over the link (client.remote_provider). An office that is not linked — a client's
server before its pair exists (Exampleu until DGO-1636) — has no door here, but this office's Computers app may
still reach its machine over ssh, with the office's own key and pinned host key (`bbox computers ssh`). Then
the verb runs THERE, in the checkout that office's containers were started from, exactly as typed here minus
`--office`: that office's own token and adapter. Nothing of theirs is copied here and nothing of ours goes
there — `--url` and `--token` are dropped, never forwarded. Output streams (follow works), and the exit
status is the remote command's. Once the office is linked, `remote_provider` finds it and this is not used.

Which computer is <office>: one whose id, label or host is the name, else the one whose office calls itself
that — the DEPLOYMENT_NAME its console's container carries (`console-exampleu` → exampleu; every office runs a
console). Asked once and remembered beside the agent's own config, per checkout.
"""
from __future__ import annotations

import base64
import os
import shlex
import subprocess
import sys
import time
from typing import Callable, Optional

from .client import REPO, AgentError, load_config, repo_key, save_config

#: The offices on a computer, and the checkout each one's containers were started from: «name<TAB>dir» lines.
PROBE = ("docker ps --filter label=com.docker.compose.service=console "
         "--format '{{.Names}}\t{{.Label \"com.docker.compose.project.working_dir\"}}'")
#: Exit status of the remote script when the computer runs no office (scripts/via.py uses the same number).
NO_CHECKOUT = 97
#: Flags of the local CLI that must not cross: `--office` is answered here, and a local URL or token means
#: nothing on the other office — a token of ours must never be presented to another office's agent.
DROP = ("--office", "--url", "--token")


def strip_local_flags(argv: list) -> list:
    """`argv` without `--office X`, `--url X`, `--token X` (or their `=` forms), everything else in order.

    argparse takes an unambiguous abbreviation (`--tok`), so an abbreviation of a dropped flag is refused
    rather than guessed at: forwarded, it would hand our token to the other office's command line. A local
    file (`-f`) means nothing on the other machine, so it is refused too."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        name = a.split("=", 1)[0]
        if name in DROP:
            skip = "=" not in a
            continue
        if name.startswith("--") and len(name) > 2 and any(d.startswith(name) for d in DROP):
            raise AgentError(f"{name}: spell the flag out in full with --office over a computer "
                             f"({', '.join(DROP)} are never sent to the other office)", 2)
        if name in ("-f", "--file") or (name.startswith("--fi") and "--file".startswith(name)):
            raise AgentError("a local file is not carried to another office's machine: put it there first", 2)
        out.append(a)
    return out


def wrapped(script: str) -> str:
    """One shell line that runs `script` on the far side whatever the hops between re-quote: the
    Computers app joins its arguments with spaces and ssh hands them to the far login shell, so the
    script travels as base64 (no quote, space or Hebrew letter to lose) and runs in `sh -c` — keeping
    the terminal as its stdin, so Ctrl-C reaches a `follow` there."""
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return f'sh -c "$(echo {b64} | base64 -d)"'


def agent_script(args: list, office: str) -> str:
    """The far side: the checkout of the office's console named `console-<office>`; on a computer that runs
    ONE office, that one (it was found by its id, label or host). Two offices and neither by that name: none."""
    return (f"L=$({PROBE}); "
            f"W=$(printf '%s\\n' \"$L\" | awk -F'\\t' -v n={shlex.quote('console-' + office.lower())} '$1==n {{print $2}}'); "
            f"[ -n \"$W\" ] || [ \"$(printf '%s\\n' \"$L\" | grep -c .)\" != 1 ] || W=$(printf '%s\\n' \"$L\" | cut -f2); "
            f"[ -n \"$W\" ] && [ -x \"$W/bbox\" ] || {{ echo 'agent: no office checkout of that name runs on this computer' >&2; exit {NO_CHECKOUT}; }}; "
            f"cd \"$W\" && exec ./bbox agent {shlex.join(args)}")


def parse_list(text: str) -> list:
    """`bbox computers ssh list` → [{id, label, host}]: `<id> <label> <user@host>[  (shared)]`, the label
    padded to 24 columns but longer when it is: read from both ends, never by column."""
    out = []
    for line in text.splitlines():
        if not line.startswith("computer_"):
            continue
        words = line.replace("(shared)", "").split()
        if len(words) < 2:
            continue
        host = words[-1].split("@")[-1] if "@" in words[-1] else ""
        label = " ".join(words[1:-1] if host else words[1:])
        out.append({"id": words[0], "label": label, "host": host})
    return out


def _bbox(args: list, timeout: Optional[float] = None, capture: bool = True) -> subprocess.CompletedProcess:
    # A probe never reads this terminal's stdin: it belongs to the command that runs after it (`… send <id> -`).
    # With a limit, the Mac's engine guest ends the command a little before this side gives up (BBOX_GUEST_TIMEOUT,
    # packaging/macos/engine.sh guest_shell, DGO-1783): a probe that runs out frees its ssh session there.
    # A passed-through command (a long session) carries no limit, not even one this process inherited.
    env = {k: v for k, v in os.environ.items() if k != "BBOX_GUEST_TIMEOUT"}
    if timeout:
        env["BBOX_GUEST_TIMEOUT"] = str(max(1, int(timeout) - 5))
    return subprocess.run([str(REPO / "bbox"), *args], capture_output=capture, text=capture, timeout=timeout,
                          stdin=subprocess.DEVNULL if capture else None, env=env)


class Finder:
    """Which computer is <office>. `run(args, timeout)` is `bbox <args>` (a parameter, for the tests)."""

    def __init__(self, run: Callable = None):
        self.run = run or (lambda args, timeout: _bbox(args, timeout))
        self.key = f"{repo_key()}::computers"

    def _remembered(self) -> dict:
        return dict((load_config().get(self.key) or {}).get("offices") or {})

    def _remember(self, offices: dict) -> None:
        cfg = load_config()
        cfg[self.key] = {"offices": offices, "at": int(time.time())}
        save_config(cfg)

    def forget(self, office: str) -> None:
        offices = self._remembered()
        if offices.pop(office.lower(), None) is not None:
            self._remember(offices)

    def find(self, office: str) -> Optional[str]:
        want = office.strip().lower()
        known = self._remembered()
        if want in known:
            return known[want]
        try:
            p = self.run(["computers", "ssh", "list"], 60)
        except subprocess.TimeoutExpired:
            raise AgentError("this office's Computers app did not list its computers in 60 s", 3)
        computers = [c for c in parse_list(p.stdout or "") if c["id"] != "computer_local-local"]
        for c in computers:
            if want in {c["id"].lower(), c["label"].lower(), c["host"].lower()}:
                return c["id"]
        # Ask each computer which offices it runs, until one answers with the name: a computer that is off or
        # refuses costs its timeout and nothing else. Every office learnt on the way is remembered.
        found = None
        for c in computers:
            try:
                q = self.run(["computers", "ssh", c["id"], wrapped(PROBE)], 30)
            except subprocess.TimeoutExpired:
                continue
            if q.returncode != 0:
                continue
            for line in (q.stdout or "").splitlines():
                name = line.split("\t")[0].strip()
                if name.startswith("console-"):
                    known[name[len("console-"):].lower()] = c["id"]
            if want in known:
                found = known[want]
                break
        self._remember(known)
        return found


def run_there(office: str, argv: list, finder: Optional[Finder] = None) -> int:
    """Run `bbox agent <argv minus local flags>` on <office>'s own machine; its exit status."""
    finder = finder or Finder()
    args = strip_local_flags(argv)                  # refused before any computer is asked
    cid = finder.find(office)
    if not cid:
        raise AgentError(f"the office {office!r} is not linked to this office, and none of its computers runs it "
                         f"(`./bbox computers ssh list`; an office is found by its id, label, host or DEPLOYMENT_NAME)", 3)
    sys.stderr.write(f"agent: {office} is not linked here — running on its computer {cid} over ssh\n")
    sys.stderr.flush()
    code = _bbox(["computers", "ssh", cid, wrapped(agent_script(args, office))], capture=False).returncode
    if code == NO_CHECKOUT:
        finder.forget(office)          # that computer no longer runs the office: ask again next time
    return code
