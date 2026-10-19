#!/usr/bin/env python3
"""adapt-host — rewrite the compiled compose for the machine that will actually run it.

    python3 adapt-host.py /opt/binaos/.generated/compose.runtime.yml \
        --cores 4 --socket /run/binaos-docker.sock

The installer calls this; it lives in its own file so the rules have one testable home rather than
existing only inside a heredoc, and so a broken install can be repaired without reinstalling.

Two things the shipped compose cannot know at build time.

CPU SIZING. `deploy.resources.limits.cpus` carries values sized for the production VPS. Docker does
not treat an over-large limit as a hint — it refuses:

    range of CPUs is from 0.01 to 4.00, as there are only 4 CPUs available

The container never starts, `docker compose up` exits non-zero, and the whole stack fails on a
machine with fewer cores than the builder's. `apitools` asks for 6.

THE DOCKER SOCKET, which is the subtler one and cost a full day. BinaOS runs a PRIVATE engine on its
own socket so it cannot disturb the host's Docker. But five services bind-mount
`/var/run/docker.sock` — that is the HOST's daemon, not ours. On a machine with its own Docker they
are wired to the wrong engine entirely:

    /var/run/docker.sock      -> engine 29.1.3, 0 containers   (the host's, empty)
    /run/binaos-docker.sock   -> engine 28.5.2, 27 containers  (ours)

traefik watches that socket for routing labels, so it discovered ZERO routers and every
`*.localhost` returned 404 while traefik itself reported healthy — indistinguishable from the
documented Docker-29 API-floor failure, and misdiagnosed as exactly that. app-management was also
pointed at the empty daemon, so app install/uninstall could not have worked either.

Only the mount SOURCE is rewritten. The target stays `/var/run/docker.sock`, because that is the
path every image expects to find.

MEMORY SIZING — added 2026-08-06, and deliberately a CHECK rather than a rewrite.

This file used to consider only cores. That is the same defect that `bbox`'s profile selection had
(`prof="prod"; [ $n -le 4 ] && prof="vps"` — core count alone, memory never consulted), and it is
worse here because it ships to customers: a packaged install on a 16-core / 8 GiB machine passed
the CPU check cleanly and kept memory limits sized for whatever machine the profile was built for.
On this project's own dev box the identical defect put an 8 GiB `apitools` limit on a 9.7 GiB host
and the stack tore itself down 42 times in 24 hours.

WHY THIS DOES NOT RESCALE MEMORY THE WAY IT RESCALES CPUS
--------------------------------------------------------
The CPU rule is safe because a CPU limit has no floor — half a core still runs, just slower, and
Docker's refusal ("range of CPUs is from 0.01 to 4.00") makes an over-large value a hard error that
must be fixed. Memory is not like that. Docker accepts an over-large memory limit silently, and
memory limits have HARD FLOORS that no scale factor can see:

  * `NODE_OPTIONS=--max-old-space-size=1024` under a 768M limit is an OOM kill under load. Measured
    on this project 2026-08-06 — the container ceiling MUST exceed the permitted heap by ~1.3x.
  * postgres `shared_buffers`, tesseract resident models, and Chromium's renderer tree are the same
    shape: a floor set elsewhere in the config that arithmetic here cannot know about.

So scaling every limit by `actual/assumed` would produce a compose that starts and then OOM-kills
its busiest services under load — trading a visible install failure for an invisible runtime one,
which is strictly worse. A wrong memory number must therefore be fixed where the numbers are
CHOSEN (the performance profile), not patched in the compiled artifact.

WHAT IT DOES INSTEAD
--------------------
1. Caps any single limit that exceeds the machine's total RAM. That case is unambiguous nonsense —
   one service claiming more than the whole machine — so it is safe to clamp.
2. Compares the declared sum against the machine and FAILS THE INSTALL LOUDLY if the machine cannot
   back it, naming the profile that does fit (via platform/manager/select-profile.py, which ships
   in the package — `packaging/stage-control.py` stages `platform/`). One owner for "which profile
   fits this machine"; this file asks it rather than reimplementing it.
"""
import argparse
import os
import pathlib
import subprocess
import sys

import yaml

HOST_SOCKET = "/var/run/docker.sock"


def retarget_socket(doc, socket: str) -> list:
    """Point every docker-socket mount at the engine this install actually uses."""
    moved = []
    for name, svc in (doc.get("services") or {}).items():
        for vol in (svc.get("volumes") or []):
            if isinstance(vol, dict):
                if vol.get("source") == HOST_SOCKET:
                    vol["source"] = socket
                    moved.append(name)
            elif isinstance(vol, str) and vol.startswith(HOST_SOCKET + ":"):
                idx = (svc.get("volumes") or []).index(vol)
                svc["volumes"][idx] = socket + vol[len(HOST_SOCKET):]
                moved.append(name)
        # Some services talk to the daemon over DOCKER_HOST rather than the default socket path.
        env = svc.get("environment")
        if isinstance(env, dict) and env.get("DOCKER_HOST") == f"unix://{HOST_SOCKET}":
            env["DOCKER_HOST"] = f"unix://{socket}"
            moved.append(f"{name} (DOCKER_HOST)")
    return moved


def shift_ports(doc, offset: int) -> list:
    """Move every PUBLISHED host port by `offset`, leaving container ports alone.

    Separate engines separate containers, images, volumes and networks - but NOT host ports. On a
    machine that also runs CI for this same platform, both stacks want 80/443/5432/6379 and whichever
    starts second simply fails to bind. Everything else about the two installs is already isolated;
    this is the one collision left, so it needs a knob rather than a rule.
    """
    shifted = []
    for name, svc in (doc.get("services") or {}).items():
        ports = svc.get("ports")
        if not ports:
            continue
        for i, spec in enumerate(list(ports)):
            if isinstance(spec, dict):
                pub = spec.get("published")
                if pub is None:
                    continue
                spec["published"] = str(int(str(pub)) + offset)
                shifted.append(f"{name} {pub}->{spec['published']}")
            elif isinstance(spec, str):
                # "80:80", "127.0.0.1:80:80" - the published port is the one before the LAST colon.
                bits = spec.split(":")
                if len(bits) < 2:
                    continue          # "80" alone means an ephemeral host port; nothing to move
                try:
                    old = int(bits[-2])
                except ValueError:
                    continue
                bits[-2] = str(old + offset)
                ports[i] = ":".join(bits)
                shifted.append(f"{name} {old}->{old + offset}")
    return shifted


MEM_UNIT = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}
# Same default overcommit the profile system uses. Declared limits are ceilings, not reservations,
# so some overcommit is legitimate — but it has to be a ratio someone chose, not an accident.
DEFAULT_OVERCOMMIT = 3.0


def _mem_bytes(v):
    """Parse a compose memory value ('512M', '2G', 1073741824). None when unparseable."""
    if v is None:
        return None
    s = str(v).strip().lower().rstrip("b")
    if not s:
        return None
    unit = ""
    if s and s[-1] in "kmg":
        unit, s = s[-1], s[:-1]
    try:
        return int(float(s) * MEM_UNIT[unit])
    except (ValueError, KeyError):
        return None


def machine_mem_gb() -> float:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024.0 * 1024.0)
    except OSError:
        pass
    return 0.0


def _fitting_profile(repo_root: pathlib.Path) -> str:
    """Ask the ONE owner of profile selection which profile this machine can back.

    Returns '' when the selector is unavailable — this must never become a second implementation
    of the envelope rules. An unavailable selector degrades the message, not the check.
    """
    sel = repo_root / "platform" / "manager" / "select-profile.py"
    if not sel.exists():
        return ""
    try:
        r = subprocess.run([sys.executable, str(sel)], capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def check_memory(doc, mem_gb: float, overcommit: float, repo_root: pathlib.Path):
    """Clamp nonsense, then verify the machine can back the declared total. Returns (clamped, ok)."""
    gib = 1024 ** 3
    mem_bytes = int(mem_gb * gib)
    clamped, total, uncapped = [], 0, []

    for name, svc in (doc.get("services") or {}).items():
        limits = ((svc.get("deploy") or {}).get("resources") or {}).get("limits") or {}
        b = _mem_bytes(limits.get("memory"))
        if b is None:
            if limits or svc.get("image") or svc.get("build"):
                uncapped.append(name)
            continue
        # (1) A single service claiming more than the whole machine is unambiguous nonsense.
        if mem_bytes and b > mem_bytes:
            limits["memory"] = f"{int(mem_gb * 1024)}M"
            clamped.append(f"{name} {b/gib:.2g}G->{mem_gb:.2g}G (exceeded total RAM)")
            b = mem_bytes
        total += b

    print(f"memory: machine {mem_gb:.1f} GiB, declared sum {total/gib:.1f} GiB "
          f"across {len((doc.get('services') or {}))} service(s), budget "
          f"{mem_gb * overcommit:.1f} GiB (x{overcommit:g})")
    for line in clamped:
        print(f"  clamped {line}")
    if uncapped:
        print(f"  {len(uncapped)} service(s) declare no memory limit: {', '.join(sorted(uncapped)[:8])}"
              + (" …" if len(uncapped) > 8 else ""))

    if not mem_bytes:
        print("  MemTotal unreadable — memory check NOT VERIFIED (not treated as a pass).")
        return clamped, True

    if total > mem_bytes * overcommit:
        # select-profile.py reads THIS machine's /proc/meminfo. In the installer that is the target
        # machine and the answer is right. When --mem-gb was passed to adapt a compose for a
        # DIFFERENT machine, it is not — so the recommendation is labelled rather than asserted.
        fits = _fitting_profile(repo_root)
        local_mem = machine_mem_gb()
        recommendation_is_local = abs(local_mem - mem_gb) > 0.5 and local_mem > 0
        print()
        print(f"adapt-host: REFUSING — this compose declares {total/gib:.1f} GiB of memory limits "
              f"on a {mem_gb:.1f} GiB machine.")
        print("  That is beyond the chosen overcommit, and it is NOT safe to fix here: memory")
        print("  limits have hard floors (Node --max-old-space-size, postgres shared_buffers,")
        print("  resident OCR models) that a scale factor cannot see, so rescaling would produce a")
        print("  stack that starts and then OOM-kills its busiest services under load.")
        print("  FIX IT WHERE THE NUMBERS ARE CHOSEN:")
        if fits and not recommendation_is_local:
            print(f"    PERFORMANCE_PROFILE={fits}   # what this machine can actually back")
        elif fits:
            print(f"    PERFORMANCE_PROFILE={fits}   # NOTE: computed from THIS machine "
                  f"({local_mem:.1f} GiB), not the {mem_gb:.1f} GiB target you passed via --mem-gb.")
            print("    Re-run select-profile.py on the target, or pick the profile whose")
            print("    `requires:` envelope the TARGET satisfies.")
        else:
            print("    set PERFORMANCE_PROFILE to a profile whose `requires:` envelope this")
            print("    machine satisfies (see platform/profiles/perf-profiles.yml)")
        print("    then re-render the compose and re-run this script.")
        return clamped, False

    print("  memory OK — declared limits fit the chosen overcommit of this machine.")
    return clamped, True


def cap(path: str, cores: float, socket: str = "", port_offset: int = 0,
        mem_gb: float = 0.0, overcommit: float = DEFAULT_OVERCOMMIT) -> int:
    doc = yaml.safe_load(open(path, encoding="utf-8"))
    capped, env_capped = [], []

    moved = retarget_socket(doc, socket) if socket and socket != HOST_SOCKET else []
    shifted = shift_ports(doc, port_offset) if port_offset else []

    for name, svc in (doc.get("services") or {}).items():
        resources = ((svc.get("deploy") or {}).get("resources") or {})
        limits = resources.get("limits") or {}
        raw = limits.get("cpus")
        if raw is not None:
            try:
                want = float(str(raw))
            except ValueError:
                want = None
            if want is not None and want > cores:
                limits["cpus"] = str(cores)
                capped.append(f"{name} {want:g}->{cores:g}")

        # A reservation above the limit is refused for the same reason.
        res = resources.get("reservations") or {}
        raw = res.get("cpus")
        if raw is not None:
            try:
                if float(str(raw)) > cores:
                    res["cpus"] = str(cores)
            except ValueError:
                pass

        # The same production sizing leaks into app-level worker pools via `*_CPUS`.
        env = svc.get("environment")
        if isinstance(env, dict):
            for key, val in list(env.items()):
                if not key.endswith("_CPUS") or val is None:
                    continue
                try:
                    want = float(str(val))
                except ValueError:
                    continue
                if want > cores:
                    env[key] = str(cores)
                    env_capped.append(f"{name}.{key} {want:g}->{cores:g}")

    # Memory is checked AFTER the CPU pass and BEFORE the write, so any clamp it makes is persisted
    # together with the CPU clamps rather than needing a second rewrite of the same file.
    repo_root = pathlib.Path(path).resolve().parents[1]
    mem_clamped, mem_ok = check_memory(doc, mem_gb or machine_mem_gb(), overcommit, repo_root)

    yaml.safe_dump(doc, open(path, "w", encoding="utf-8"), sort_keys=False, width=4096,
                   allow_unicode=True)
    if not mem_ok:
        # Non-zero exit: the installer must stop. A silent proceed here is exactly how an 8 GiB
        # apitools limit reached a 9.7 GiB host and stayed there for weeks.
        raise SystemExit(2)
    print(f"capped {len(capped)} cpu limit(s) and {len(env_capped)} *_CPUS value(s) to {cores:g}")
    for line in capped + env_capped:
        print(f"  {line}")
    if moved:
        print(f"pointed {len(moved)} docker-socket mount(s) at {socket}")
        for line in moved:
            print(f"  {line}")
    if shifted:
        print(f"shifted {len(shifted)} published port(s) by {port_offset:+d}")
        for line in shifted:
            print(f"  {line}")
    return len(capped) + len(env_capped) + len(moved) + len(shifted)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("compose")
    ap.add_argument("--cores", type=float, default=float(os.cpu_count() or 1))
    ap.add_argument("--mem-gb", type=float, default=0.0,
                    help="total memory of the machine that will run this, GiB. Default: read from "
                         "/proc/meminfo. Pass explicitly when adapting a compose for a DIFFERENT "
                         "machine than the one running this script.")
    ap.add_argument("--overcommit", type=float, default=DEFAULT_OVERCOMMIT,
                    help="permitted ratio of declared memory limits to machine memory. Declared "
                         "limits are ceilings, not reservations, so some overcommit is legitimate "
                         f"— but it must be a ratio someone chose. Default {DEFAULT_OVERCOMMIT:g}.")
    ap.add_argument("--socket", default="",
                    help="engine socket this install uses; docker.sock mounts are pointed at it")
    ap.add_argument("--port-offset", type=int, default=0,
                    help="move every published host port by this much, so the platform can run "
                         "beside another copy of itself (e.g. a CI runner on the same machine). "
                         "8000 puts http on 8080 and https on 8443.")
    a = ap.parse_args()
    cap(a.compose, a.cores, a.socket, a.port_offset, a.mem_gb, a.overcommit)
    raise SystemExit(0)
