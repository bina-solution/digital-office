"""app-management.admission — may these apps be PLACED on that office? (DGO-27, plan §11 decision 10)

Placement moves a running app from one office to another. Every other guard in this app answers "is
the declaration legal"; this one answers the question that actually stops a placement: **does the
destination machine have room**. It is deliberately NOT a scheduler — there is no queue, no scoring
and no automatic choice of destination (that is decision 10's "no automatic scheduler in this
version"). It is one refusal, with the numbers, before anything moves.

What it is measured against, and why each number is the one it is
----------------------------------------------------------------
* **Memory** — the destination's `available`, not its `total`. A machine can be large and still have
  nothing to give: measured on this deployment's own box, 8 GB total with 1.1 GB available, because
  the office itself lives there. Asking for `total` would have approved every placement onto a machine
  that was already out of memory. The need is the sum of the apps' own declared `resources.memory`
  plus a headroom percentage, because a container's LIMIT is not its working set: the peak is what
  kills the destination, and the peak is why the office's own rule is "leave room".
* **CPU** — load per core, not core count. A 2-core box at load 8 has no capacity to give away, and
  its core count says nothing about that. The same arithmetic the office already uses for its own
  heavy jobs (`load1 > 20` on the home box) is applied per core here, so a 2-core remote is refused
  at load 2 while a 16-core one is not — the number that matters is the ratio.
* **Disk** — the destination's free space must stay above `DGO_PLACE_MIN_FREE_MB` after the images
  this office would pull. Images are not in the apps' declarations (an app names its image, not its
  size), so this is a floor rather than a sum: the same shape `bbox` uses before it builds anything
  ("`df -h /` < 6GB → do not build"). A measured floor beats an invented per-app size table.

The three refusals are sentences with numbers in them — "there is 1.1 GB, you asked for 2.4 GB" is
actionable, "insufficient resources" is not — and they are Hebrew, because the screen that shows them
is the owner's.

Why this module is pure
-----------------------
`check()` takes the machine record and the app list as plain dicts and touches nothing: no HTTP, no
files, no clock. So the refusal can be tested with three literals (`test_admission.py`), and the
same function is the one that answers for a real machine — not a second implementation that agrees
with the test and not with the fleet.

Who calls it (2026-10-05). It was written beside the link app, for a mover that reached the
destination's machine through `computers`, and for a year only a gate measured with it. Its caller
is the control plane of the office that would RECEIVE the app: `GET /api/apps/<id>/room` answers
with this office's own memory, load and disk (read from inside its container — no door to the
machine), the apps screen shows that answer for every office it offers, and a move asks the
destination before it exports a byte. That is why the module lives here: the base cannot import an
app, and the question is the receiving office's to answer about itself.
"""
from __future__ import annotations

import os
import re

#: Free disk the destination must keep AFTER the placement. Same order as `bbox`'s own floor before a
#: build: an image pull that fills the destination's disk takes down the office that lives there.
MIN_FREE_MB = 4096
#: Memory headroom, in percent of the apps' declared limits. A limit is a ceiling, not a working set.
MEM_HEADROOM_PCT = 20
#: Load per core the destination may be at and still receive an app. Above 1.0 the machine is already
#: behind, and placing onto it moves a slow app rather than an idle one.
MAX_LOAD_PER_CPU = 1.0
#: The machine UNDER the office, where the office runs in a VM: free memory the host must keep, as an
#: amount and as a share — whichever is larger. The VM's own "available" says nothing about it:
#: measured 2026-10-06, the VM had 3.7 GB available while Windows had 275 MB free (1.7%) and the VM
#: stopped answering for two minutes. The same margin the machine screen paints red.
HOST_MIN_FREE_MB = 1024
HOST_MIN_FREE_PCT = 8

_UNITS = {"": 1, "b": 1 / (1024 * 1024), "k": 1 / 1024, "kb": 1 / 1024, "kib": 1 / 1024,
          "m": 1, "mb": 1, "mib": 1, "g": 1024, "gb": 1024, "gib": 1024,
          "t": 1024 * 1024, "tb": 1024 * 1024, "tib": 1024 * 1024}


def _env_num(name: str, default, cast=float):
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return cast(float(raw))
    except ValueError:
        return default


def mib(value) -> float:
    """A Docker-style size string (`160M`, `1G`, `512MiB`) or a number, in MiB.

    The apps' declarations carry `resources.memory` as the string Docker itself takes, so this is the
    one place that translation happens — a second parser that disagrees would approve a placement the
    destination cannot hold.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]*)\s*$", str(value))
    if not m:
        return 0.0
    n, unit = float(m.group(1)), m.group(2).lower()
    return n * _UNITS.get(unit, 1)


def need(apps: list[dict]) -> dict:
    """What the placement asks for: the apps' own declared limits, summed.

    Taken from each app's `resources` block — the app's own words, not a table kept here — so an app
    that raises its own limit raises what the destination must have, with no second file to update.
    """
    mem = sum(mib((a.get("resources") or {}).get("memory") or a.get("memory")) for a in apps)
    cpu = sum(float((a.get("resources") or {}).get("cpus") or a.get("cpus") or 0) for a in apps)
    return {"memory_mb": round(mem, 1), "cpus": round(cpu, 2), "apps": len(apps)}


def have(machine: dict) -> dict:
    """What the destination has to give, from the `computers` record, spelled in MiB."""
    mem = machine.get("memory") or {}
    disk = machine.get("disk") or {}
    host = machine.get("host") or {}
    ncpu = int(machine.get("ncpu") or 0)
    load1 = load_1(machine.get("load"))
    return {
        "memory_available_mb": round(float(mem.get("available") or 0) / (1024 * 1024), 1),
        "memory_total_mb": round(float(mem.get("total") or 0) / (1024 * 1024), 1),
        "disk_available_mb": round(float(disk.get("available") or 0) / (1024 * 1024), 1),
        # the machine under a VM, when a host-side part of the office reports it — else None
        "host_free_mb": (round(float(host["mem_free"]) / (1024 * 1024), 1) if host.get("mem_total") else None),
        "host_total_mb": (round(float(host["mem_total"]) / (1024 * 1024), 1) if host.get("mem_total") else None),
        "ncpu": ncpu,
        "load1": load1,
        "load_per_cpu": round(load1 / ncpu, 2) if ncpu else None,
    }


def load_1(value) -> float:
    """The 1-minute load average out of `computers`' own `"1.63 1.92 2.55"` spelling."""
    if isinstance(value, (int, float)):
        return float(value)
    for part in str(value or "").split():
        try:
            return float(part)
        except ValueError:
            continue
    return 0.0


def _gb(mb: float) -> str:
    """Sizes as a person reads them. Below a gigabyte the MiB are the honest number."""
    return f"{mb / 1024:.1f}GB" if mb >= 1024 else f"{mb:.0f}MB"


def check(machine: dict, apps: list[dict], *, min_free_mb: float | None = None,
          mem_headroom_pct: float | None = None, max_load_per_cpu: float | None = None) -> dict:
    """The one answer: may these apps run on that machine?

    Returns `{ok, need, have, problems[], summary}`. `problems` is a list of refusals, each a code and
    a Hebrew sentence WITH the numbers — a caller that only wants the verdict reads `ok`, and a caller
    that shows it to the owner prints `summary`.
    """
    min_free = _env_num("DGO_PLACE_MIN_FREE_MB", MIN_FREE_MB) if min_free_mb is None else min_free_mb
    headroom = (_env_num("DGO_PLACE_MEM_HEADROOM_PCT", MEM_HEADROOM_PCT)
                if mem_headroom_pct is None else mem_headroom_pct)
    max_lpc = (_env_num("DGO_PLACE_MAX_LOAD_PER_CPU", MAX_LOAD_PER_CPU)
               if max_load_per_cpu is None else max_load_per_cpu)

    n, h = need(apps), have(machine)
    problems: list[dict] = []
    want_mem = n["memory_mb"] * (1 + headroom / 100.0)

    if not machine:
        problems.append({"code": "unreachable",
                         "he": "אין מידע על המכונה ביעד — לא נבדקה קבלה"})
    elif not h["memory_total_mb"]:
        # A record with no memory in it is a machine that was never probed. Refusing beats assuming.
        problems.append({"code": "unprobed",
                         "he": "המכונה ביעד לא נבדקה בפועל — רענן את הבדיקה ונסה שוב"})
    else:
        if h["memory_available_mb"] < want_mem:
            problems.append({
                "code": "memory",
                "he": (f"אין מקום בזיכרון ביעד: נדרש {_gb(want_mem)} "
                       f"({_gb(n['memory_mb'])} + {headroom:.0f}% מרווח), "
                       f"ויש {_gb(h['memory_available_mb'])} פנויים "
                       f"מתוך {_gb(h['memory_total_mb'])}")})
        if h["host_free_mb"] is not None and h["host_free_mb"] < max(
                HOST_MIN_FREE_MB, h["host_total_mb"] * HOST_MIN_FREE_PCT / 100.0):
            problems.append({
                "code": "host_memory",
                "he": (f"המחשב שמריץ את הלשכה כמעט בלי זיכרון פנוי: נשארו {_gb(h['host_free_mb'])} "
                       f"מתוך {_gb(h['host_total_mb'])}. הלשכה רצה בתוך מכונה וירטואלית, והזיכרון "
                       "שהיא רואה אצלה אינו כל התמונה")})
        if h["load_per_cpu"] is not None and h["load_per_cpu"] > max_lpc:
            problems.append({
                "code": "cpu",
                "he": (f"היעד עסוק מדי: עומס {h['load1']:.2f} על {h['ncpu']} ליבות "
                       f"= {h['load_per_cpu']:.2f} לליבה, והמקסימום הוא {max_lpc:.2f}")})
        if h["disk_available_mb"] < min_free:
            problems.append({
                "code": "disk",
                "he": (f"אין מקום בדיסק ביעד: נדרש להשאיר {_gb(min_free)} פנויים אחרי ההצבה, "
                       f"ויש {_gb(h['disk_available_mb'])}")})

    if not apps:
        problems.append({"code": "empty", "he": "לא נבחרה אפליקציה להצבה"})

    ok = not problems
    return {
        "ok": ok,
        "need": n,
        "have": h,
        "limits": {"min_free_mb": min_free, "mem_headroom_pct": headroom,
                   "max_load_per_cpu": max_lpc},
        "problems": problems,
        "summary": (f"אפשר להציב {n['apps']} אפליקציות ב{_gb(n['memory_mb'])} זיכרון"
                    if ok else " · ".join(p["he"] for p in problems)),
    }


def check_machine(machine: dict, apps: list[dict], **kw) -> dict:
    """`check()` for a caller that holds a machine id and asks `computers` for the record.

    Kept here rather than in the route so the route and the converge use ONE verdict: the machine
    record is fetched through the same door as everything else in this app (`computers`), and a fetch
    that fails is a refusal that says so — never a silent approval.
    """
    if not machine or machine.get("error"):
        return check({}, apps, **kw)
    return check({k: machine.get(k) for k in
                  ("hostname", "os", "ncpu", "load", "memory", "disk", "host")}, apps, **kw)
