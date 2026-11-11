#!/usr/bin/env python3
"""test_stale_containers.py — lib.sh's stale_containers reads compose's dry run in every shape compose prints it.

    python3 scripts/test_stale_containers.py

Compose 2.40 prefixes every dry-run line with «DRY-RUN MODE -», and the parser wanted «Container» as the first word: it
read EVERY dry run as nothing to recreate (measured 2026-11-11 on the MacBook — 22 to recreate, «none» said;
issues/compose-prefixes-its-dry-run-lines-so-stale-containers-reads-every-dry-run-as-nothing-to-recreate.yaml). The
lines below are compose v2.40.3's own, captured that morning inside app-management-local, plus the older unprefixed
shape. lib.sh is sourced in bash with compose stood in by a function that prints them.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
fails = 0


def check(name, cond, got=None):
    global fails
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"   got {got!r}"))
    fails += 0 if cond else 1


if not shutil.which("bash") or subprocess.run(["bash", "-c", "[ \"${BASH_VERSINFO[0]}\" -ge 4 ]"]).returncode:
    print("NOT RUN needs bash 4 (lib.sh)")
    sys.exit(1)

V2_40 = """ DRY-RUN MODE -  Container lan-signin-local  Recreate
 DRY-RUN MODE -  Container n8n-postgres-local  Recreate
 DRY-RUN MODE -  Container dgo-net-local  Running
 DRY-RUN MODE -  Container console-local  Recreate
 DRY-RUN MODE -  Container dgo-link-local  Running
 DRY-RUN MODE -  Container redis-local  Recreate
 DRY-RUN MODE -  Container \x1b[32mapp-management-local\x1b[0m  Recreate
 DRY-RUN MODE -  Container forge-local  Recreated
 DRY-RUN MODE -  Network traefik-network  Created
 DRY-RUN MODE -  Container browser42-mcp-local  Error response from daemon: No such image
time="2026-11-11T07:25:00+03:00" level=warning msg="The \\"POSTGRES_PASSWORD\\" variable is not set."
"""
OLD = """Container lan-signin-local  Recreate
Container dgo-net-local  Running
 Container redis-local  Recreate
"""


def stale(lines: str, rc: int = 0) -> tuple[list, int]:
    script = (f'. "{ROOT}/scripts/lib.sh" >/dev/null 2>&1\n'
              'export_host_tz() { :; }; export_cert_resolver() { :; }; ccr_clamp_nofile() { :; }\n'
              f'_dcx_run_for() {{ printf "%s" "$DRY"; return {rc}; }}\n'
              'stale_containers')
    r = subprocess.run(["bash", "-c", script], env=dict(os.environ, DRY=lines), capture_output=True, text=True,
                       timeout=60)
    return r.stdout.split(), r.returncode


got, rc = stale(V2_40)
check("compose 2.40's prefixed lines: every container it would recreate, and none it keeps running",
      got == sorted(["app-management-local", "console-local", "lan-signin-local", "n8n-postgres-local",
                     "redis-local"]) and rc == 0, got)
got, rc = stale(OLD)
check("the older unprefixed shape still reads the same way", got == ["lan-signin-local", "redis-local"], got)
got, rc = stale(" DRY-RUN MODE -  Container dgo-net-local  Running\n")
check("nothing to recreate is an empty answer", got == [] and rc == 0, got)
got, rc = stale(V2_40, rc=124)
check("a dry run past its bound is «could not tell» (rc 3), never «none»", rc == 3, rc)
script = (f'. "{ROOT}/scripts/lib.sh" >/dev/null 2>&1\n'
          'export_host_tz() { :; }; export_cert_resolver() { :; }; ccr_clamp_nofile() { :; }\n'
          '_dcx_run_for() { printf "%s" "$DRY"; return 1; }\n'
          'stale_containers')
r = subprocess.run(["bash", "-c", script], env=dict(os.environ, DRY=V2_40), capture_output=True, text=True, timeout=60)
check("a dry run compose STOPPED partway says the list may be partial, and why (stage 1: the names, rc 0)",
      r.returncode == 0 and "redis-local" in r.stdout and "exited 1 — the list may be partial" in r.stderr
      and "No such image" in r.stderr and "browser42-mcp-local" in r.stderr and "exited 1" not in r.stdout,
      (r.returncode, r.stderr[-200:]))
r = subprocess.run(["bash", "-c", script], env=dict(os.environ, DRY=" DRY-RUN MODE -  Container redis-local  Recreate\n"
                                                                    "compose stopped here\n"),
                   capture_output=True, text=True, timeout=60)
check("…and with no error line in it, the last thing compose said", "partial: compose stopped here" in r.stderr,
      r.stderr[-200:])

print("stale containers: " + ("PASS" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
