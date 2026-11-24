#!/usr/bin/env python3
"""test_bbox_status_checks.py — `bbox status` never dies on a check it cannot make (DGO-2003).

The status block is read out of bbox itself (`  status)` … the next verb) and run under the file's own
`set -euo pipefail` with PATH empty and nothing defined, so every command it ACTUALLY runs (lib.sh's probes, docker,
nft, the plumbing) falls into bash's command_not_found_handle, which logs it and answers as a healthy office. Then
each logged command is made to fail in turn:
    every one but need_docker (the precondition)   → the status still reaches its last line (the n8n brief), exit 0,
                                                     and a check that failed says so in its own line (SAYS)
    nft refused (exit 1), as in Bina Claude's container → «firewall: not readable from here»
    nft failing any other way                       → its own first error line, never «from here»
    nft crashed (exit 139)                          → the DGO-1358 line, which a crash used to kill before it printed
    need_docker                                     → stops: with no engine there is nothing to report
A scan that finds fewer commands than the ones named here fails: a test that ran nothing is not a pass.
Needs bash and nothing else; G72 reads scripts/test_*.py.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

BBOX = pathlib.Path(__file__).resolve().parent.parent / "bbox"
MUST_RUN = {"docker", "awk", "foreign_containers", "image_drift", "shared_hosts", "shared_names", "stale_images", "nft",
            "need_docker"}

PRE = r"""set -euo pipefail
DN=office; cg=; cy=; cr=; c0=; c1=; FORCE=
PATH=/nonexistent
command() { if [ "${1:-}" = -v ]; then echo "$2"; return 0; fi; builtin command "$@"; }
command_not_found_handle() {
  local n="$1"; shift
  echo "$n" >> "$CALLS"
  # a stub reads what is piped to it, as the real command does: one that left early would SIGPIPE its writer, and
  # under pipefail that is a failure of the test's own making
  drain() { while IFS= read -r _; do :; done; }
  if [ "$n" = "${FAIL:-}" ]; then drain; echo "partial output of $n"; echo "${FAILERR:-}" >&2; return "${FAILRC:-1}"; fi
  # the plumbing is the real thing (a grep that always matched would make the nft lines pass by themselves)
  case "$n" in awk|sed|grep|head|tr|python3) builtin command -p "$n" "$@"; return ;; esac
  drain
  if [ "$n" = bash ] && [[ "${1:-}" == */apps/n8n/hooks/status ]]; then echo END-REACHED; return 0; fi
  case "$n" in
    say) echo "[bbox] $*" ;;
    id) echo 0 ;;
    docker) [ "${1:-}" = ps ] && printf 'console-office\tUp 1 hour (healthy)\tconsole\n' ;;
  esac
  return 0
}
"""


def block() -> str:
    lines = BBOX.read_text(encoding="utf-8").splitlines()
    s = next(i for i, l in enumerate(lines) if l == "  status)")
    e = next(i for i in range(s + 1, len(lines)) if re.match(r"^  [a-z][a-z-]*\)", lines[i]))
    body = lines[s + 1:e]
    body[-1] = re.sub(r";;\s*$", "", body[-1])
    return "\n".join(body) + "\n"


#: the line each check owes when it fails (bbox: not_checked); the rest of what status runs owes only its survival
SAYS = {
    "docker": "the running list (docker ps): not checked",
    "awk": "the count: not checked",
    "foreign_containers": "names another compose project holds: not checked",
    "image_drift": "images older than their tag: not checked",
    "shared_hosts": "routing rules more than one container claims: not checked",
    "shared_names": "names more than one container answers to: not checked",
    "stale_images": "images older than their sources: not checked",
}


def run(work: pathlib.Path, script: pathlib.Path, fail: str = "", rc: int = 1, err: str = ""):
    calls = work / "calls"
    calls.unlink(missing_ok=True)
    env = {**os.environ, "CALLS": str(calls), "FAIL": fail, "FAILRC": str(rc), "FAILERR": err}
    r = subprocess.run(["bash", str(script)], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env,
                       timeout=60)
    out = r.stdout + r.stderr
    ran = set(calls.read_text().split()) if calls.exists() else set()
    return r.returncode, out, ran


def main() -> int:
    if not shutil.which("bash"):
        print("NOT RUN no bash on this machine")
        return 1
    bad = 0

    def check(ok: bool, what: str, out: str = ""):
        nonlocal bad
        print(("PASS  " if ok else "FAIL  ") + what)
        if not ok:
            bad += 1
            print("\n".join("        " + l for l in out.splitlines()[-12:]))

    with tempfile.TemporaryDirectory() as t:
        work = pathlib.Path(t)
        hook = work / "repo/apps/n8n/hooks/status"
        hook.parent.mkdir(parents=True)
        hook.write_text("")
        hook.chmod(0o755)
        script = work / "status.sh"
        script.write_text(f"REPO_ROOT={work / 'repo'}\n" + PRE + block())
        if subprocess.run(["bash", "-n", str(script)]).returncode:
            print("FAIL  the status block read out of bbox does not parse")
            return 1
        rc, out, ran = run(work, script)
        check(rc == 0 and "END-REACHED" in out, "a healthy office: the status reaches its last line, exit 0", out)
        missing = MUST_RUN - ran
        check(not missing, f"the scan found the commands the status runs ({len(ran)}: {' '.join(sorted(ran))})"
              + (f"; missing {' '.join(sorted(missing))}" if missing else ""))
        for c in sorted(ran - {"bash", "need_docker"}):
            rc, out, _ = run(work, script, c)
            check(rc == 0 and "END-REACHED" in out, f"{c} fails: the status still prints to its end, exit 0", out)
            if c in SAYS:
                check(SAYS[c] in out, f"…and says «{SAYS[c]}»", out)
        rc, out, _ = run(work, script, "docker")
        check("containers: " not in out, "a docker ps that failed is not counted as «0 up / 0 declared on»", out)
        rc, out, _ = run(work, script, "nft", 1, "Error: Operation not permitted (you must be root)")
        check(rc == 0 and "firewall: not readable from here" in out and "END-REACHED" in out,
              "nft refused (no NET_ADMIN): «firewall: not readable from here», and the status goes on", out)
        rc, out, _ = run(work, script, "nft", 1, "Error: Could not process rule: No such file or directory")
        check(rc == 0 and "firewall: nft failed (exit 1): Error: Could not process rule" in out
              and "not readable from here" not in out, "nft failing otherwise: its own error, not «from here»", out)
        rc, out, _ = run(work, script, "nft", 139)
        check(rc == 0 and "cannot read its own ruleset (exit 139)" in out and "END-REACHED" in out,
              "nft crashed: the DGO-1358 line is said, and the status goes on", out)
        rc, out, _ = run(work, script, "need_docker")
        check(rc != 0 and "END-REACHED" not in out, "need_docker fails: the status stops (the precondition)", out)
    print("test_bbox_status_checks: " + ("ok" if not bad else f"{bad} FAILED"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
