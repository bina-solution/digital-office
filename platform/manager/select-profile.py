#!/usr/bin/env python3
"""select-profile — resolve the performance profile from the machine's actual resources.

    python3 platform/manager/select-profile.py            # prints the profile name
    python3 platform/manager/select-profile.py --explain   # prints the reasoning table

THE ONE OWNER OF "WHICH PROFILE DOES THIS MACHINE GET".

Prints exactly one profile name on stdout so a shell can consume it, or nothing (exit 1) if it
cannot decide — callers must treat "no answer" as "use the floor profile", never as "use prod".

WHY THIS FILE EXISTS
--------------------
Selection used to live in `bbox:202` as:

    prof="prod"; [ $n -le 4 ] && prof="vps"; [ $n -le 2 ] && prof="ci-small"

Core count alone. Memory was never consulted — even though every profile in perf-profiles.yml has
always declared `host_mem`. The data was there and the selector never asked for it.

Measured consequence on this deployment (2026-08-06): 6 cores + a 9.7 GiB WSL2 VM selected `prod`,
which declares `host_mem: 16G`. The stack was sized for a machine with 65% more memory than it has.
Sum of declared container limits reached 4.46x physical, the VM ran itself out of memory against a
Windows host with 1.27 GiB free, and the WSL distro was torn down 42 times in 24 hours — each
teardown orphaning every in-flight n8n execution and mislabelling them as OOM.

A 6-core/10 GB box and a 6-core/32 GB box must not get the same profile. That is the whole point.

WHY AN ENVELOPE RATHER THAN MORE BRANCHES
-----------------------------------------
Adding `[ $mem -lt X ] && prof=...` would reproduce the original defect in a new shape: sizing
knowledge spread across a shell script that has to be edited every time a profile is added. Each
profile instead declares the machine it needs (`requires: {cores, mem_gb}`) and this file picks the
richest profile the machine satisfies. Adding a profile needs no change here and no change in bbox.

WHICH MEMORY
------------
The DOCKER HOST's memory — the WSL2 VM under Windows, the box itself on native Linux. Not the
Windows host's total: containers land in the VM, and the VM's ceiling is what they must fit inside.
On WSL that ceiling is set by .wslconfig `memory=`, and /proc/meminfo MemTotal reports it correctly.
"""
import os
import re
import sys
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
YML = REPO / "platform" / "profiles" / "perf-profiles.yml"

# The floor. If nothing else fits, this is the answer — never the largest profile. Under-sizing
# costs speed; over-sizing is what took the host down 42 times.
FLOOR = "ci-small"


def parse_profiles(path):
    """Minimal reader for the profile file's `requires:` and `host_mem:` lines.

    Deliberately does NOT import PyYAML: this runs from `bbox` during bring-up, on machines where
    the venv may not exist yet, and a missing dependency here would fail profile selection at the
    worst possible moment. It reads only the two keys it needs.

    NOTE: scripts/perf-profile-apply has its own parser for the `env:`/`settings:` blocks. That is
    a known duplication, tracked in the sizing-ownership table; consolidating the two parsers is a
    separate change from consolidating the SELECTION logic, and mixing them would make this
    reviewable-in-one-sitting change into a rewrite.
    """
    profiles = {}
    cur = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.lstrip().startswith("#"):
            continue
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0 and line.rstrip().endswith(":"):
            cur = line.strip().rstrip(":")
            profiles[cur] = {}
            continue
        if cur is None:
            continue
        m = re.match(r"\s*requires:\s*\{(.+?)\}", line)
        if m:
            body = m.group(1)
            c = re.search(r"cores:\s*([0-9.]+)", body)
            g = re.search(r"mem_gb:\s*([0-9.]+)", body)
            profiles[cur]["cores"] = float(c.group(1)) if c else 0.0
            profiles[cur]["mem_gb"] = float(g.group(1)) if g else 0.0
            continue
        m = re.match(r"\s*host_mem:\s*([0-9.]+)\s*G", line)
        if m:
            profiles[cur]["host_mem_gb"] = float(m.group(1))
    return profiles


def machine_cores() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 1


def machine_mem_gb() -> float:
    """Total memory of the machine containers actually run on."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024.0 * 1024.0)
    except OSError:
        pass
    return 0.0


def select(profiles, cores, mem_gb):
    """Richest profile whose envelope the machine satisfies, on BOTH axes.

    "Richest" = largest declared host_mem, i.e. the profile that asks the most of the machine while
    still fitting inside it. Ties break on the larger core requirement, then name, so the result is
    deterministic and a reordered file cannot change the answer.
    """
    fits = [
        (name, p) for name, p in profiles.items()
        if "cores" in p and cores >= p["cores"] and mem_gb >= p["mem_gb"]
    ]
    if not fits:
        return None, fits
    fits.sort(key=lambda kv: (kv[1].get("host_mem_gb", 0), kv[1].get("cores", 0), kv[0]),
              reverse=True)
    return fits[0][0], fits


def main():
    explain = "--explain" in sys.argv
    if not YML.exists():
        print(f"select-profile: {YML} not found", file=sys.stderr)
        return 1
    profiles = parse_profiles(YML)
    sized = {k: v for k, v in profiles.items() if "cores" in v}
    if not sized:
        print("select-profile: no profile declares a `requires:` envelope", file=sys.stderr)
        return 1

    cores, mem_gb = machine_cores(), machine_mem_gb()
    if mem_gb <= 0:
        print("select-profile: could not read machine memory", file=sys.stderr)
        return 1

    chosen, fits = select(sized, cores, mem_gb)

    if explain:
        print(f"machine: {cores} cores, {mem_gb:.1f} GiB (docker host)")
        print(f"{'profile':<12} {'needs_cores':>11} {'needs_mem_gb':>12} {'host_mem':>9}  fits")
        for name, p in sorted(sized.items(), key=lambda kv: kv[1].get("host_mem_gb", 0)):
            ok = cores >= p["cores"] and mem_gb >= p["mem_gb"]
            why = "yes" if ok else (
                "no (cores)" if cores < p["cores"] else "no (memory)")
            print(f"{name:<12} {p['cores']:>11g} {p['mem_gb']:>12g} "
                  f"{p.get('host_mem_gb', 0):>8g}G  {why}")
        print(f"\nselected: {chosen or FLOOR}"
              f"{'' if chosen else '  (nothing fit — floor profile)'}")
        return 0

    if chosen is None:
        # Smaller than every declared envelope. Answer the floor rather than nothing, so a very
        # small machine still boots with sane sizing instead of falling back to `prod`.
        print(FLOOR)
        return 0
    print(chosen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
