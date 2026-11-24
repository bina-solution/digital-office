#!/usr/bin/env python3
"""single-file-bind-lint — gate G119: no compose mounts a single tracked file into a container (DGO-2111 root 13).

    python3 scripts/refactor/single-file-bind-lint.py              # warn: each such mount, named; exit 0
    python3 scripts/refactor/single-file-bind-lint.py --strict     # …and exit 1 while one is left (the next stage)
    python3 scripts/refactor/single-file-bind-lint.py --self-test  # prove each finding can be made, on fixtures

WHY THIS EXISTS. A bind mount of a FILE follows the inode it was given. git, and every editor that writes atomically,
replaces a file with a new inode, so a running container keeps the old one. Through a shared mount (the Mac's engine,
the HP's C: over 9p) the old one is simply gone:
- 2026-11-10: browser42's task runner on the Mac lost three of its four files after batch 33's merge
  (issues/a-single-file-bind-mount-goes-stale-…yaml);
- 2026-11-18: the HP's n8n workers failed «can't open '/worker-liveness.sh': I/O error», the breakers tripped, and
  the reaper and the task watchdog could not start (DGO-2111 root 13).
A DIRECTORY mount follows the directory and sees the new file. The fix per app is to mount its directory read-only and
run the files from there (notify-relay and github-hooks do).

WHAT IT READS: every apps/*/docker-compose.yml and platform-base/*/docker-compose.yml, each service's `volumes:`,
short (`./x.sh:/x.sh:ro`) and long (`type: bind, source: ./x.sh`). A finding is a source that is relative to the
compose file, carries no `${…}`, and names a FILE tracked by git. A directory, a named volume, an absolute host path
(/var/run/docker.sock, /proc) and an untracked or generated file are not findings: git never replaces them.
It prints what it scanned (the files, the services, the binds); scanning no compose file fails at every stage.

STAGES (GATES.md, «Tightening a contract»): it warns and exits 0, with the findings as the work list (77 on
2026-11-22, in 30 apps, of 181 relative binds in 146 services). `--strict` fails on any, for when each app has moved to a directory mount. Each app's move is
its own lane's (recreating its containers is that app's step).
"""
from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]


def tracked(root: Path) -> set[str]:
    p = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True)
    if p.returncode != 0:
        return set()
    return {x for x in p.stdout.decode("utf-8", "replace").split("\0") if x}


def _sources(volumes) -> list[str]:
    out = []
    for v in volumes or []:
        if isinstance(v, str):
            src = v.split(":", 1)[0] if ":" in v else ""
            out.append(src)
        elif isinstance(v, dict) and str(v.get("type") or "bind") == "bind":
            out.append(str(v.get("source") or ""))
    return out


def scan(root: Path, files: set[str] | None = None) -> tuple[list[tuple[str, str, str]], dict]:
    """(findings: compose path, service, source), and what was read."""
    files = tracked(root) if files is None else files
    composes = sorted(list(root.glob("apps/*/docker-compose.yml")) + list(root.glob("platform-base/*/docker-compose.yml")))
    if not composes:                        # green and blind must never look alike (G66): a wrong root fails here
        raise SystemExit(f"G119 FAIL — no apps/*/ or platform-base/*/docker-compose.yml under {root}: "
                         f"a wrong root is no pass")
    seen = {"files": 0, "services": 0, "binds": 0, "unreadable": []}
    found: list[tuple[str, str, str]] = []
    for c in composes:
        try:
            doc = yaml.safe_load(c.read_text(encoding="utf-8")) or {}
        except Exception as e:  # noqa: BLE001 — a compose this cannot read is named, never skipped silently
            seen["unreadable"].append(f"{c.relative_to(root)}: {type(e).__name__}")
            continue
        seen["files"] += 1
        for name, svc in (doc.get("services") or {}).items():
            if not isinstance(svc, dict):
                continue
            seen["services"] += 1
            for src in _sources(svc.get("volumes")):
                if not src.startswith(("./", "../")) or "$" in src:
                    continue
                seen["binds"] += 1
                rel = (c.parent / src).resolve()
                try:
                    key = rel.relative_to(root.resolve()).as_posix()
                except ValueError:
                    continue
                if key in files and rel.is_file():
                    found.append((str(c.relative_to(root)), str(name), src))
    return found, seen


def report(found, seen, strict: bool) -> int:
    if not seen["files"]:
        print("G119 FAIL — no compose file was read: a wrong root is no pass")
        return 1
    per: dict[str, int] = {}
    for c, _, _ in found:
        per[c] = per.get(c, 0) + 1
    for c, svc, src in found:
        print(f"  {c}  {svc}: {src}")
    for u in seen["unreadable"]:
        print(f"  ! unreadable {u}")
    head = (f"G119 — {seen['files']} compose file(s), {seen['services']} service(s), {seen['binds']} relative bind(s) "
            f"read: {len(found)} mount a single tracked file, in {len(per)} app(s)")
    if found and strict:
        print(head.replace("G119", "G119 FAIL", 1))
        return 1
    print(head.replace("G119", "G119 PASS (warn)" if found else "G119 PASS", 1))
    if found:
        print("  stage 1 warns (DGO-2111 root 13): mount the app's directory read-only instead; --strict fails on them")
    return 0


def self_test() -> int:
    fails = []
    with tempfile.TemporaryDirectory() as t:
        r = Path(t)
        a = r / "apps" / "demo"
        (a / "bin").mkdir(parents=True)
        for f in ("run.sh", "tool.py", "long.sh", "bin/x.sh"):
            (a / f).write_text("echo\n")
        (r / "platform-base" / "base").mkdir(parents=True)
        (a / "docker-compose.yml").write_text(
            "services:\n"
            "  one:\n    image: x\n    volumes:\n"
            "      - ./run.sh:/run.sh:ro\n"            # a tracked file: FOUND
            "      - ./bin:/bin:ro\n"                  # a directory: fine
            "      - ./:/app:ro\n"                     # the app's directory: fine
            "      - data:/data\n"                     # a named volume: fine
            "      - /var/run/docker.sock:/var/run/docker.sock\n"   # an absolute host path: fine
            "      - ./untracked.sh:/u.sh\n"           # not tracked: fine
            "      - ${X:-./tool.py}:/t.py\n"          # a variable: fine (not decidable here)
            "  two:\n    image: x\n    volumes:\n"
            "      - type: bind\n        source: ./long.sh\n        target: /long.sh\n"   # long syntax: FOUND
            "      - type: volume\n        source: data\n        target: /d\n"
            "volumes:\n  data:\n")
        (r / "platform-base" / "base" / "docker-compose.yml").write_text(
            "services:\n  b:\n    image: x\n    volumes:\n      - ../../apps/demo/tool.py:/tool.py\n")   # FOUND
        files = {"apps/demo/run.sh", "apps/demo/tool.py", "apps/demo/long.sh", "apps/demo/bin/x.sh"}
        found, seen = scan(r, files)
        got = sorted((c, s, src) for c, s, src in found)
        want = sorted([("apps/demo/docker-compose.yml", "one", "./run.sh"),
                       ("apps/demo/docker-compose.yml", "two", "./long.sh"),
                       ("platform-base/base/docker-compose.yml", "b", "../../apps/demo/tool.py")])
        if got != want:
            fails.append(f"findings: {got}")
        if seen["files"] != 2 or seen["services"] != 3:
            fails.append(f"read: {seen}")
        with contextlib.redirect_stdout(io.StringIO()):     # the stages' own lines are not this run's verdict
            stages = (report(found, seen, strict=False), report(found, seen, strict=True),
                      report([], {"files": 0, "services": 0, "binds": 0, "unreadable": []}, strict=False))
        if stages[:2] != (0, 1):
            fails.append("the stages: warn exits 0, --strict exits 1")
        if stages[2] != 1:
            fails.append("no compose read must fail at every stage")
    print(f"single-file-bind-lint self-test: {'7/7 outcomes told apart' if not fails else 'FAIL ' + '; '.join(fails)}")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    found, seen = scan(ROOT)
    return report(found, seen, strict="--strict" in argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
