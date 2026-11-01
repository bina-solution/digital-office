"""sites.machines — the ONE door to a machine, and it is the `computers` service's.

A site does not run here. It runs on a machine: the office host, a server the owner attached over
SSH, or a VPS. This app therefore owns no SSH key, no address and no host list — every fact about a
machine, and every command that runs on one, goes through `apps/computers`
(`ai/context/platform-service-contract.md` §1: the vault is the one copy of the fleet).

What that buys, concretely: the sites app cannot invent a machine, cannot reach a machine the owner
has not approved the office key on, and cannot outlive the computers app's own audit trail. If
`computers` is down, this returns a REASON rather than an empty fleet — "no machines" and "the fleet
service is unreachable" are different facts and only one of them means the owner has no servers.
"""
from __future__ import annotations

import json
import logging
import os
import shlex

import requests

log = logging.getLogger("sites.machines")

COMPUTERS_URL = os.environ.get("COMPUTERS_URL", "http://computers:8977").rstrip("/")
LIST_TIMEOUT = float(os.environ.get("SITES_MACHINE_LIST_TIMEOUT", "25"))
DEFAULT_TIMEOUT = int(os.environ.get("SITES_EXEC_TIMEOUT", "120"))
MAX_TIMEOUT = 600


class MachineError(Exception):
    """A machine action that did not happen, with the sentence to show the owner."""

    def __init__(self, message: str, *, machine: str | None = None, detail: str | None = None,
                 status: int = 502):
        super().__init__(message)
        self.message = message
        self.machine = machine
        self.detail = detail
        self.status = status

    def body(self) -> dict:
        out = {"error": self.message, "machine": self.machine}
        if self.detail:
            out["detail"] = self.detail
        return out


def list_machines(probe: bool = False) -> tuple[list[dict], str | None]:
    """(machines, error). The error is RETURNED, never swallowed: an unreachable fleet service and
    an empty fleet look identical otherwise, and the owner would be told "you have no computers"."""
    try:
        r = requests.get(f"{COMPUTERS_URL}/api/computers", params={"probe": 1 if probe else 0},
                         timeout=LIST_TIMEOUT)
        r.raise_for_status()
        body = r.json() or {}
        return list(body.get("computers") or []), None
    except requests.RequestException as e:
        log.warning("computers service unreachable: %s", type(e).__name__)
        return [], "שירות המחשבים אינו זמין"
    except ValueError:
        return [], "שירות המחשבים החזיר תשובה שאינה JSON"


def machine(machine_id: str, probe: bool = False) -> dict:
    machines, err = list_machines(probe=probe)
    if err:
        raise MachineError(err, machine=machine_id)
    m = next((x for x in machines if x.get("id") == machine_id), None)
    if not m:
        raise MachineError(f"המחשב {machine_id!r} אינו ברשימת המחשבים של הלשכה", machine=machine_id,
                           status=404)
    return m


def exec_on(machine_id: str, command: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run a shell command ON a machine. Returns the computers app's own result dict.

    `{code, stdout, stderr, timed_out, state, reason, action}` — `code` is the remote shell's real
    exit code, so a caller can distinguish "the command said no" from "the machine said nothing".
    Failures are NOT raised here: a scan that could not run is a finding, not an exception.
    """
    timeout = max(1, min(MAX_TIMEOUT, int(timeout or DEFAULT_TIMEOUT)))
    try:
        r = requests.post(f"{COMPUTERS_URL}/api/computers/{machine_id}/exec",
                          json={"command": command, "timeout": timeout},
                          timeout=timeout + 20)
    except requests.RequestException as e:
        return {"code": None, "stdout": "", "stderr": str(e), "timed_out": False, "state": "error",
                "reason": "שירות המחשבים אינו זמין",
                "action": "בדוק שהאפליקציה „מחשבים” פועלת."}
    if r.status_code >= 300:
        try:
            detail = r.json()
        except ValueError:
            detail = {"raw": r.text[:400]}
        return {"code": None, "stdout": "", "stderr": json.dumps(detail, ensure_ascii=False),
                "timed_out": False, "state": "error",
                "reason": (detail or {}).get("error") or f"המחשבים החזירו {r.status_code}"}
    try:
        return r.json() or {}
    except ValueError:
        return {"code": None, "stdout": "", "stderr": r.text[:400], "timed_out": False,
                "state": "error", "reason": "המחשבים החזירו תשובה שאינה JSON"}


def run(machine_id: str, command: str, timeout: int = DEFAULT_TIMEOUT,
        what: str = "הפקודה") -> dict:
    """`exec_on` + the house rule: an action that failed must RAISE, not return a success shape.

    A caller that mutates a machine (deploy, start, stop) uses this; a caller that only reads
    (status, logs, scans) uses `exec_on` and reports what came back. Both exist because the two
    mistakes are different: silently ignoring a failed deploy, and aborting a scan because grep
    exited 1.
    """
    res = exec_on(machine_id, command, timeout)
    code = res.get("code")
    if code != 0:
        reason = res.get("reason") or f"{what} הסתיימה בקוד {code}"
        tail = (res.get("stderr") or res.get("stdout") or "")[-1500:]
        raise MachineError(reason, machine=machine_id, detail=tail,
                           status=409 if res.get("state") == "needs_action" else 502)
    return res


def stdout_of(machine_id: str, command: str, timeout: int = DEFAULT_TIMEOUT,
              default: str = "") -> str:
    """Read-only helper: the command's stdout, or `default` when it could not be run at all."""
    res = exec_on(machine_id, command, timeout)
    if res.get("code") in (0, None) and res.get("stdout"):
        return res["stdout"]
    if res.get("stdout"):
        return res["stdout"]          # partial output beats nothing (grep exits 1 on no match)
    return default


def q(text: str) -> str:
    """shell-quote one value. Everything the owner types (hostnames, paths, labels) passes here
    before it reaches a remote shell, and `shlex.quote` is the only quoting this app trusts."""
    return shlex.quote(text)


def write_file(machine_id: str, path: str, content: str, mode: int = 0o644,
               timeout: int = DEFAULT_TIMEOUT) -> None:
    """Write a file on the machine.

    base64 through stdin, not a heredoc: the content is YAML/nginx config the owner also edits, and
    a heredoc re-opens every quoting question a config file asks ($variables, backticks, quotes).
    `base64 -d` is coreutils and present on every machine this office attaches to.
    """
    import base64
    payload = base64.b64encode(content.encode("utf-8")).decode("ascii")
    cmd = (f"mkdir -p {q(os.path.dirname(path))} && "
           f"printf '%s' {q(payload)} | base64 -d > {q(path)} && chmod {mode:o} {q(path)}")
    run(machine_id, cmd, timeout, what=f"כתיבת {path}")
