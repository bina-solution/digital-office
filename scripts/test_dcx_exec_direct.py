#!/usr/bin/env python3
"""test_dcx_exec_direct.py — `dcx exec -T` reaches a running container without parsing the office's compose (DGO-1148).

    python3 scripts/test_dcx_exec_direct.py        (G72 runs it; bash and python3 only)

Every `dcx exec` ran reconcile.py compose-files and parsed the whole office (~60 apps) only to find one container,
and a Plane call made two or three of them (measured 2026-11-02 on the Mac: the engine at load 60–110). dcx now
asks compose's own labels (this project, that service) and runs `docker exec -i` when exactly one container
answers, and goes the long way otherwise. This lifts `_dcx_exec_direct` and `dcx` out of scripts/lib.sh as they
are, stubs docker and every step of the compose path, and holds which calls take which way — and that what the
short way runs is what compose exec would have: the same options, the same service, the same command, stdin
passed, the command's exit code returned. On the code before DGO-1148 the short-way cases fail.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FAILS: list[str] = []


def function(src: str, name: str) -> str:
    m = re.search(r"^" + re.escape(name) + r"\(\) \{\n.*?^\}\n", src, re.M | re.S)
    return m.group(0) if m else ""


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n        {detail}"))
    if not ok:
        FAILS.append(name)


SRC = (REPO / "scripts" / "lib.sh").read_text(encoding="utf-8")
FUNCS = function(SRC, "_dcx_exec_direct") + function(SRC, "dcx")
STUBS = r"""
LOG="$1"; RUNNING="$2"; PROJECT="$3"; PS_FAILS="$4"; shift 4
COMPOSE_PROJECT_NAME="$PROJECT"
BBOX_COMPOSE="$(command -v bash)"          # any executable: dcx only checks that the plugin is there
docker() {
  if [ "$1" = ps ]; then
    [ "$PS_FAILS" = 1 ] && return 1
    case "$*" in *" -a"*|*"--all"*) echo "PS-ALL" >> "$LOG" ;; esac
    case "$*" in *"label=com.docker.compose.project=office"*"label=com.docker.compose.service=pln"*) ;; *) return 0 ;; esac
    [ -z "$RUNNING" ] || printf '%s\n' ${RUNNING//,/ }
    return 0
  fi
  echo "DOCKER $*" >> "$LOG"
  [ "$1" = exec ] && { input="$(cat)"; echo "STDIN ${input}" >> "$LOG"; }
  return 7
}
die() { echo "DIE $*" >> "$LOG"; exit 9; }
_dcx_run() { echo "COMPOSE $*" >> "$LOG"; return 5; }
for f in export_host_tz export_cert_resolver bbox_assert_engine_socket compose_admit deploy_ledger_gate \
         deploy_ledger_record cpu_caps_apply netns_rejoin filemount_refresh image_refresh; do eval "$f() { :; }"; done
compose_is_recreate() { return 1; }
compose_is_up() { return 1; }
compose_self_guard() { return 1; }
"""


def run(*argv: str, running: str = "abc123", project: str = "office", ps_fails: bool = False, stdin: str = "",
        mode: str = "set -uo pipefail") -> tuple[int, list[str]]:
    with tempfile.NamedTemporaryFile("r", delete=False) as fh:
        log = Path(fh.name)
    script = mode + "\n" + STUBS + FUNCS + '\ndcx "$@"\necho "AFTER rc=$?" >> "$LOG"\n'
    r = subprocess.run(["bash", "-c", script, "bash", str(log), running, project, "1" if ps_fails else "0", *argv],
                       input=stdin, capture_output=True, text=True, timeout=30)
    lines = log.read_text().splitlines()
    log.unlink()
    return r.returncode, lines


def short(log: list[str]) -> bool:
    return any(ln.startswith("DOCKER exec") for ln in log) and not any(ln.startswith("COMPOSE") for ln in log)


def main() -> int:
    check("lib.sh has _dcx_exec_direct and dcx", "_dcx_exec_direct() {" in FUNCS and "\ndcx() {" in "\n" + FUNCS)

    rc, log = run("exec", "-T", "-e", "A=1", "--env", "B=2", "-u", "me", "-w", "/x", "pln", "python3", "-", "x y",
                  stdin="body")
    check("exec -T with -e/--env/-u/-w: docker exec -i in the one container, the command and its arguments whole",
          log[:1] == ["DOCKER exec -i -e A=1 --env B=2 -u me -w /x abc123 python3 - x y"] and "STDIN body" in log, repr(log))
    check("…and the command's exit code is dcx's", "AFTER rc=7" in log, repr(log))
    rc, log = run("exec", "-T", "--env=C=3", "--user=u", "--workdir=/w", "pln", "sh", "-c", "")
    check("the --opt=value forms ride along, and an empty argument survives",
          log[:1] == ["DOCKER exec -i --env=C=3 --user=u --workdir=/w abc123 sh -c "], repr(log))
    rc, log = run("exec", "-T", "pln", "false", mode="set -euo pipefail")
    check("under set -e a failing command ends the script with its own code", rc == 7 and short(log)
          and not any(ln.startswith("AFTER") for ln in log), f"rc={rc} {log!r}")
    check("only RUNNING containers are asked (no `docker ps -a`)", "PS-ALL" not in log, repr(log))

    for name, kw, argv in (
            ("no -T (a TTY): through compose", {}, ("exec", "pln", "sh")),
            ("an option it does not carry (--index): through compose", {}, ("exec", "-T", "--index", "2", "pln", "sh")),
            ("-e KEY with no value (compose reads .env too): through compose", {}, ("exec", "-T", "-e", "FOO", "pln", "sh")),
            ("--env=KEY with no value: through compose", {}, ("exec", "-T", "--env=FOO", "pln", "sh")),
            ("a dangling -e: through compose", {}, ("exec", "-T", "-e")),
            ("no running container: through compose", {"running": ""}, ("exec", "-T", "pln", "sh")),
            ("two running containers: through compose", {"running": "a1,b2"}, ("exec", "-T", "pln", "sh")),
            ("another service: through compose", {}, ("exec", "-T", "other", "sh")),
            ("no COMPOSE_PROJECT_NAME: through compose", {"project": ""}, ("exec", "-T", "pln", "sh")),
            ("another project: through compose", {"project": "elsewhere"}, ("exec", "-T", "pln", "sh")),
            ("docker ps fails: through compose", {"ps_fails": True}, ("exec", "-T", "pln", "sh")),
            ("not exec: through compose", {}, ("ps",)),
            ("exec with no command: through compose", {}, ("exec", "-T", "pln"))):
        rc, log = run(*argv, **kw)
        check(name, any(ln.startswith("COMPOSE " + " ".join(argv)) for ln in log)
              and not any(ln.startswith("DOCKER exec") for ln in log) and "AFTER rc=5" in log, f"rc={rc} {log!r}")

    print(f"\n{'all passed' if not FAILS else f'{len(FAILS)} failed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
