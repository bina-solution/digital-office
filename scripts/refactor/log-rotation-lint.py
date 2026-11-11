#!/usr/bin/env python3
"""log-rotation-lint — gate G111: no container's log is unbounded on any office.

G111 since the release that took hp-dgo (DGO-969, 2026-11-10); it was G99 on hp-dgo, a number dgo-stable had
already given no-phone-home-lint.

    python3 scripts/refactor/log-rotation-lint.py
    python3 scripts/refactor/log-rotation-lint.py --self-test

WHY. Docker's `json-file` driver keeps a container's log for ever unless it is told not to. The
platform mostly tells it (95 of 114 services declare `max-size`/`max-file` in their own compose,
1m-10m x 1-3 files), but the ones that did not were the ones that write the most: measured on the HP
2026-11-09 (DGO-1393), `plane-db` wrote **1.2 MB a minute - 815 MB in one day** — because
`log_min_duration_statement=150ms` on a machine whose load makes ordinary statements slow. The log was
not what made the machine slow; it was what turned a slow machine into a full disk. The office cannot
legislate what each app's service logs — it CAN legislate how much of it the disk keeps.

THE SHAPE. Two halves, one question ("is this service bounded?"):

  * an app MAY bound its own log in its own compose, and its choice stands (the values differ on
    purpose — a 1m x 1 service and a 10m x 3 one both count);
  * whatever an app does NOT bound, the COMPILER bounds: `platform/manager/reconcile.py` renders
    `.generated/logging.override.yml` for exactly the services that declare nothing, and
    `compose_files()` passes it, so an office cannot differ from another office and a new app cannot
    forget.

WHAT THIS GATE ASKS, and it asks it of the CODE, not of a comment:

  1. **a declaration that bounds nothing** — `logging:` with an empty, missing or `0` `max-size`/
     `max-file` is an unbounded log with extra steps. Only a driver that writes a LOCAL FILE is
     judged: `journald`, `syslog`, `awslogs`, `none` and friends keep no file here to bound.
  2. **every service is covered** — app-declared bounds OR the compiler's overlay, never neither.
  3. **the compiler's own pipeline** — `_services_without_logging()` must find exactly the services
     that declare nothing (in a THROWAWAY compile, so the live `.generated/` is never written),
     `render_logging()` must write an overlay naming exactly those, and `compose_files()`'s RETURNED
     list must contain it. A gate that grepped the source for the file name could be satisfied by the
     comment that mentions it; this one runs the pipeline and reads the answer.

It prints what it scanned and touches nothing of the office: the pipeline check builds its own
`compose.yml` + app compose + overlay in one temporary directory under the repo, and removes it.
"""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import sys
import tempfile

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = "G111"

#: Drivers that keep the log somewhere that is NOT a file on this host. `json-file`, `local` and an
#: EMPTY driver (Docker's default is json-file) are the ones a `max-size` is about.
NOT_A_LOCAL_FILE = {"none", "journald", "syslog", "awslogs", "gelf", "fluentd", "splunk",
                    "gcplogs", "logentries", "sumologic", "etwlogs"}


def composes() -> list[pathlib.Path]:
    return sorted(REPO.glob("apps/*/docker-compose.yml")) + sorted(REPO.glob("platform-base/*/docker-compose.yml"))


def load_reconcile():
    """The compiler. Imported for its pure functions and run in a throwaway compile — never rendered here."""
    spec = importlib.util.spec_from_file_location(
        "reconcile_for_log_rotation", REPO / "platform" / "manager" / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def driver_of(logging) -> str:
    d = str((logging or {}).get("driver") or "").strip()
    # `${LOGGING_DRIVER:-json-file}` is the office's own switch and is json-file unless somebody
    # changes it for a reason; judge it as the file driver it is today.
    return "json-file" if d.startswith("${") or not d else d


def bounds_of(logging) -> tuple[str, str]:
    opts = (logging or {}).get("options") or {}
    return str(opts.get("max-size") or "").strip(), str(opts.get("max-file") or "").strip()


def scan(files=None) -> tuple[list[str], dict]:
    """Findings from the composes alone (the app half), and what each service declares."""
    files = composes() if files is None else files
    findings: list[str] = []
    declared: dict[str, tuple[pathlib.Path, object]] = {}
    for f in files:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            findings.append(f"{f}: unparseable: {exc}")
            continue
        for name, body in (doc.get("services") or {}).items():
            declared[name] = (f, (body or {}).get("logging"))
    for name, (where, logging) in sorted(declared.items()):
        if logging is None or driver_of(logging) in NOT_A_LOCAL_FILE:
            continue
        size, count = bounds_of(logging)
        for key, value in (("max-size", size), ("max-file", count)):
            if not value or value == "0":
                findings.append(f"{where}: service '{name}' declares `logging:` (driver "
                                f"{driver_of(logging)}) with no {key} — an unbounded log with extra steps")
    return findings, declared


def coverage(declared: dict, rec) -> list[str]:
    """Nothing may be left unbounded: app-declared bounds, else the compiler's overlay."""
    gap = {n for n, (_w, lg) in declared.items() if lg is None}
    if not hasattr(rec, "logging_overlay"):
        return [f"{len(gap)} service(s) declare no `logging:` of their own and the compiler has no "
                f"logging_overlay() at all — every one of them is unbounded"]
    covered = ((yaml.safe_load(rec.logging_overlay(gap)) or {}).get("services") or {})
    out = []
    for name in sorted(gap):
        if name not in covered:
            out.append(f"service '{name}' declares no `logging:` of its own and the compiler's "
                       f"overlay does not name it — its log is unbounded")
    return out


def pipeline(rec) -> list[str]:
    """Run the COMPILER's half for real, in a throwaway compile: what it finds, what it writes, and
    whether compose is handed the file. The live `.generated/` is never written."""
    if not (hasattr(rec, "logging_overlay") and hasattr(rec, "render_logging")
            and hasattr(rec, "_services_without_logging")):
        return []            # coverage() already reports the missing function by name
    tmp = REPO / (".gate99-" + next(tempfile._get_candidate_names()))
    tmp.mkdir(parents=True, exist_ok=False)
    real_gen = rec.GEN
    try:
        app = tmp / "app-docker-compose.yml"
        app.write_text("services:\n"
                       "  bounded-by-app:\n"
                       "    logging: {driver: json-file, options: {max-size: 2m, max-file: '2'}}\n"
                       "  left-to-the-compiler:\n"
                       "    image: x\n", encoding="utf-8")
        (tmp / "compose.yml").write_text("include:\n  - %s\n" % app.as_posix(), encoding="utf-8")
        rec.GEN = tmp
        findings: list[str] = []
        found = rec._services_without_logging()
        if found != {"left-to-the-compiler"}:
            findings.append(f"_services_without_logging() returned {sorted(found)} in a throwaway "
                            f"compile where exactly ['left-to-the-compiler'] declares nothing — the "
                            f"names the overlay is built from are wrong")
        rec.render_logging()
        overlay = tmp / "logging.override.yml"
        if not overlay.exists():
            findings.append("render_logging() wrote no logging.override.yml for a service that "
                            "declares nothing — the bounds never reach compose")
        else:
            names = sorted(((yaml.safe_load(overlay.read_text(encoding="utf-8")) or {})
                            .get("services") or {}))
            if names != ["left-to-the-compiler"]:
                findings.append(f"the overlay names {names}, not exactly the service that declares "
                                f"nothing — it overrides an app's own bound or misses one")
        if not any(str(f).endswith("logging.override.yml") for f in rec.compose_files()):
            findings.append("compose_files()'s returned list does not contain logging.override.yml — "
                            "a file compose is never given bounds nothing")
        return findings
    finally:
        rec.GEN = real_gen
        shutil.rmtree(tmp, ignore_errors=True)


def self_test() -> int:
    """Fixtures in a temp directory, never in the repo's compiled tree."""
    rec = load_reconcile()
    bad = 0
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="gate99-"))
    try:
        def case(label: str, yaml_text: str, want: int) -> None:
            nonlocal bad
            f = tmp / "case.yml"
            f.write_text(yaml_text, encoding="utf-8")
            got, declared = scan([f])
            got += coverage(declared, rec)
            if len(got) != want:
                print(f"  SELFTEST FAIL  {label}: expected {want} finding(s), got {len(got)}: {got}")
                bad += 1
            else:
                print(f"  selftest ok    {label}")

        case("an app bounds its own log (the values are the app's)",
             "services:\n  a:\n    logging: {driver: json-file, options: {max-size: 1m, max-file: '1'}}\n", 0)
        case("an app declares logging but no bounds at all (two findings, one per key)",
             "services:\n  a:\n    logging: {driver: json-file}\n", 2)
        case("an app declares max-file 0",
             "services:\n  a:\n    logging: {driver: json-file, options: {max-size: 5m, max-file: '0'}}\n", 1)
        case("a driver that keeps no local file is not judged",
             "services:\n  a:\n    logging: {driver: journald}\n", 0)
        case("no app logging — the compiler fills it",
             "services:\n  a:\n    image: x\n", 0)
        # a producer that FORGETS a service is exactly the failure this gate exists for
        original = rec.logging_overlay
        rec.logging_overlay = lambda names: original(set(names) - {"a"})
        try:
            case("the compiler forgets a service", "services:\n  a:\n    image: x\n", 1)
        finally:
            rec.logging_overlay = original
        # …and the compiler's whole half, run for real in a throwaway compile
        pipe = pipeline(rec)
        if pipe:
            print(f"  SELFTEST FAIL  the compiler's pipeline: {pipe}")
            bad += 1
        else:
            print("  selftest ok    the compiler's pipeline (found, wrote, and compose is given it)")
        return 1 if bad else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    findings, declared = scan()
    rec = load_reconcile()
    findings += coverage(declared, rec)
    findings += pipeline(rec)
    gap = sum(1 for _w, lg in declared.values() if lg is None)
    print(f"{GATE} log-rotation-lint: {len(declared)} service(s) — "
          f"{len(declared) - gap} bound their own log, {gap} are bound by the compiler")
    if findings:
        print(f"{GATE} FAIL — {len(findings)} finding(s):")
        for f in findings[:40]:
            print(f"  - {f}")
        return 1
    print(f"{GATE} PASS — every service's log is bounded, and the compiler hands compose its overlay")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
