#!/usr/bin/env python3
"""test_disk_floor.py — the disk floor every heavy job passes (scripts/lib.sh disk_free_gb, disk_reclaim, disk_admit).

    python3 scripts/test_disk_floor.py

WHY (DGO-1393). On 2026-11-05 the HP's Windows drive C: was at 100% (3.2 GB of 476 GB free) and every build, image pull
and recording of five parallel sessions stopped there; on 2026-10-15 the same drive at 2.3 GB had the WSL VM stopped from
outside for three hours (DGO-625). Nothing looked at the disk before starting a heavy job, and inside the VM the engine's
ext4 read 865 GB free while the drive that holds it was full.

What is held, with `df` and `docker` played by stubs on PATH (a temp dir — the engine of the machine that runs this is
never asked anything, and nothing of it is pruned):
  * the emptier of the checkout's filesystem and the engine's is the number that counts;
  * above the floor: admitted, nothing pruned;
  * under it: the rebuildable is given back first — dangling images and the build cache above its cap — and the job is
    admitted when that made room;
  * still under it: refused and said where the office declares BBOX_DISK_ENFORCE=1 (environment or .env), and started
    with a warning everywhere else — warn first, then refuse (AGENTS.md, «tightening a contract»); either way nothing but
    those two prunes ran (no volume, no tagged image, no container);
  * the prune after a take (disk_reclaim without --cache) gives back the dangling images only: the build cache keeps
    its weekly prune;
  * the floor is BBOX_DISK_MIN_GB from the environment or .env; else 20 for a checkout on a Windows drive under WSL
    (/mnt/<drive>/…, where the drive also holds the .vhdx) and 5 anywhere else; 0 turns it off; a nested heavy step
    passes on BBOX_DISK_ADMITTED; a disk that cannot be read admits.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]

DF = """#!/bin/sh
# df -Pk <path>: the free GiB of $STUB/free.repo for the checkout, $STUB/free.engine for anything else
[ -e "$STUB/df.broken" ] && exit 1
case "$2" in "$REPO_UNDER_TEST"*) f="$STUB/free.repo" ;; *) f="$STUB/free.engine" ;; esac
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "/dev/x 1000000000 1 $(( $(cat "$f") * 1048576 )) 1% /"
"""

DOCKER = """#!/bin/sh
echo "$*" >> "$STUB/calls"
case "$*" in
  "info --format {{.DockerRootDir}}") echo "$STUB/engine-root" ;;
  "image prune -f") [ -f "$STUB/repo.after.prune" ] && cp "$STUB/repo.after.prune" "$STUB/free.repo"; true ;;
  "builder prune -f --keep-storage "*) true ;;
  *) exit 1 ;;
esac
"""


def run(stub: pathlib.Path, repo: str, script: str, env: dict | None = None) -> tuple[int, str]:
    e = {k: v for k, v in os.environ.items() if not k.startswith("BBOX_")}
    e.update({"PATH": f"{stub / 'bin'}:{os.environ.get('PATH', '')}", "STUB": str(stub),
              "REPO_ROOT": str(repo), "REPO_UNDER_TEST": str(repo), "NO_COLOR": "1"})
    e.update(env or {})
    p = subprocess.run(["bash", "-c", f'. "{REPO}/scripts/lib.sh" >/dev/null 2>&1; {script}'],
                       env=e, capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


def case(repo_gb: int, engine_gb: int, script: str = 'disk_admit "a build"; echo "rc=$?"', after_prune: int | None = None,
         env: dict | None = None, dotenv: str = "", broken: bool = False, repo_root: str = "") -> tuple[str, list[str]]:
    with tempfile.TemporaryDirectory() as t:
        base = pathlib.Path(t).resolve()   # the physical path: lib.sh resolves REPO_ROOT with pwd -P
        stub, repo = base / "stub", base / "repo"
        (stub / "bin").mkdir(parents=True)
        (stub / "engine-root").mkdir()
        repo.mkdir()
        for name, body in (("df", DF), ("docker", DOCKER)):
            (stub / "bin" / name).write_text(body)
            (stub / "bin" / name).chmod(0o755)
        (stub / "free.repo").write_text(f"{repo_gb}\n")
        (stub / "free.engine").write_text(f"{engine_gb}\n")
        if after_prune is not None:
            (stub / "repo.after.prune").write_text(f"{after_prune}\n")
        if dotenv:
            (repo / ".env").write_text(dotenv)
        if broken:
            (stub / "df.broken").write_text("")
        _, out = run(stub, repo_root or str(repo), script, env)
        calls = (stub / "calls").read_text().splitlines() if (stub / "calls").exists() else []
        return out, calls


fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1
        for line in detail.splitlines()[-8:]:
            print("      | " + line)


def prunes(calls: list[str]) -> list[str]:
    return [c for c in calls if "prune" in c or " rm" in f" {c}" or "rmi" in c or "volume" in c]


# WSL: the checkout is on C: (3 GiB free), the engine's ext4 reads 865 GiB free — the 3 is the truth
out, calls = case(3, 865, 'disk_free_gb')
check("the emptier filesystem counts (C: 3, ext4 865 → 3)", out.strip() == "3", out)
out, calls = case(865, 7, 'disk_free_gb')
check("…whichever of the two it is (engine 7 → 7)", out.strip() == "7", out)

out, calls = case(50, 865)
check("above the floor: admitted, nothing pruned", "rc=0" in out and not prunes(calls), out + "\n".join(calls))

out, calls = case(3, 865, after_prune=40)
check("under the floor: the rebuildable given back, then admitted",
      "rc=0" in out and prunes(calls) == ["image prune -f", "builder prune -f --keep-storage 10GB"], out + "\n".join(calls))

ENFORCE = {"BBOX_DISK_ENFORCE": "1"}
out, calls = case(3, 865, env=ENFORCE)
check("still under the floor, enforced: refused, and said", "rc=1" in out and "is not started" in out and "floor of 5 GiB" in out,
      out)
check("…and nothing but the two prunes ran (no volume, no tagged image, no container)",
      prunes(calls) == ["image prune -f", "builder prune -f --keep-storage 10GB"], "\n".join(calls))

out, calls = case(3, 865)
check("still under the floor, not enforced: started, with the warning", "rc=0" in out and "starts with only 3 GiB" in out
      and prunes(calls) == ["image prune -f", "builder prune -f --keep-storage 10GB"], out + "\n".join(calls))
out, calls = case(3, 865, dotenv="BBOX_DISK_ENFORCE=1\n")
check("BBOX_DISK_ENFORCE=1 in .env is the office's declaration", "rc=1" in out and "is not started" in out, out)
out, calls = case(12, 865, repo_root="/mnt/c/Users/t/MyDGO", env=ENFORCE)
check("a checkout on a Windows drive under WSL: the floor is 20 (12 GiB refused)", "rc=1" in out and "floor of 20 GiB" in out, out)
out, calls = case(12, 865)
check("anywhere else the floor is 5 (12 GiB admitted)", "rc=0" in out and not prunes(calls), out)

out, calls = case(3, 865, env={"BBOX_DISK_MIN_GB": "0"})
check("BBOX_DISK_MIN_GB=0: admitted, nothing pruned", "rc=0" in out and not prunes(calls), out)
out, calls = case(12, 865, dotenv="BBOX_DISK_MIN_GB=15\n", env=ENFORCE)
check("the floor from .env (15): 12 GiB refused, where the default would admit", "rc=1" in out and "floor of 15 GiB" in out, out)
out, calls = case(12, 865, dotenv="BBOX_DISK_MIN_GB=15\n", env={"BBOX_DISK_MIN_GB": "10"})
check("the environment wins over .env (10): 12 GiB admitted", "rc=0" in out, out)
out, calls = case(3, 865, dotenv="BBOX_BUILD_CACHE_GB=4\n")
check("the build cache cap from .env (4 GB)", "builder prune -f --keep-storage 4GB" in calls, "\n".join(calls))
out, calls = case(50, 865, script='disk_reclaim')
check("the prune after a take: dangling images only, the build cache kept", prunes(calls) == ["image prune -f"], "\n".join(calls))

out, calls = case(3, 865, env=ENFORCE,
                  script='disk_admit "a build" >/dev/null 2>&1; BBOX_DISK_ADMITTED=1 disk_admit "its nested build"; echo "rc=$?"')
check("a nested heavy step passes on BBOX_DISK_ADMITTED", out.strip().endswith("rc=0"), out)
out, calls = case(50, 865, script='disk_admit "a build" >/dev/null 2>&1; bash -c "echo admitted=\\${BBOX_DISK_ADMITTED:-}"')
check("an admission is exported to the job's children (read in a child process)", "admitted=1" in out, out)
out, calls = case(3, 865, env={**ENFORCE, "BBOX_HEAVY": "off"},
                  script='compose_admit build web; echo "rc=$?"; compose_admit up -d web; echo "recreate=$?"; echo after')
check("a refused build returns to its caller (said there), and a recreate is never refused for the disk",
      "rc=1" in out and "recreate=0" in out and "after" in out and "is not started" in out, out)
out, calls = case(3, 865, broken=True, env=ENFORCE)
check("a disk that cannot be read admits (the check is not the job)", "rc=0" in out and not prunes(calls), out)

print()
print(f"{fails} failing")
sys.exit(1 if fails else 0)
