#!/usr/bin/env python3
"""DGO-27 · unit tests for `admission.py` — the placement admission check.

    python3 platform-base/app-management/test_admission.py

Pure literals, no machine, no HTTP: the module's whole point is that the verdict is a function of two
dicts, so the refusals can be proven here and the fleet is only the caller. Each check returns
(ok, measured-text) and is also importable as a list by the link app's `tests/phase2.py`, so that gate runs
these without a second copy of them.

The refusals are tested for their NUMBERS as well as their verdict: "insufficient resources" is the
failure mode this check exists to avoid, so a message that does not carry the amount it saw is a
failing test, not a cosmetic one.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("dgo_admission", APP / "admission.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


admission = _load()

CHECKS: list = []


def check(name):
    def deco(fn):
        fn._check_name = name
        CHECKS.append(fn)
        return fn
    return deco


# ── the machines these checks measure against ────────────────────────────────────
def machine(*, ncpu=4, load1=0.5, mem_total_mb=15000, mem_avail_mb=9000,
            disk_avail_mb=40000, **extra) -> dict:
    """A `computers` status record, spelled the way that app really spells it (bytes, not MiB)."""
    m = {
        "hostname": "portable", "os": "Ubuntu 24.04 LTS", "ncpu": ncpu,
        "load": f"{load1:.2f} 0.40 0.30",
        "memory": {"total": mem_total_mb * 1024 * 1024, "used": (mem_total_mb - mem_avail_mb) * 1024 * 1024,
                   "available": mem_avail_mb * 1024 * 1024, "used_percent": 40.0},
        "disk": {"total": 100000 * 1024 * 1024, "used": (100000 - disk_avail_mb) * 1024 * 1024,
                 "available": disk_avail_mb * 1024 * 1024, "used_percent": 60.0},
    }
    m.update(extra)
    return m


#: app.json's own shape — `resources` is what the app declares about itself.
def app(aid: str, memory: str = "256M", cpus: str = "0.3") -> dict:
    return {"id": aid, "resources": {"memory": memory, "cpus": cpus}}


# ── the checks ───────────────────────────────────────────────────────────────────
@check("DGO-27 · a roomy destination accepts, and says what it needs")
def c_accept():
    r = admission.check(machine(), [app("browser42", "900M", "1.0"), app("n8n", "512M", "1.0")])
    ok = r["ok"] and r["need"]["apps"] == 2 and r["need"]["memory_mb"] == 1412.0
    return ok, (f"ok={r['ok']} need={r['need']} have={ {k: r['have'][k] for k in ('memory_available_mb','load_per_cpu','disk_available_mb')} }"
                if ok else f"refused a roomy destination: {r['summary']}")


@check("DGO-27 · low memory refuses, and the sentence carries BOTH numbers")
def c_memory():
    # 900 MiB needed + 20% = 1080 MiB, and the destination has 800.
    r = admission.check(machine(mem_avail_mb=800), [app("browser42", "900M", "1.0")])
    codes = [p["code"] for p in r["problems"]]
    he = next((p["he"] for p in r["problems"] if p["code"] == "memory"), "")
    ok = (not r["ok"] and codes == ["memory"] and "1.1GB" in he and "800MB" in he)
    return ok, f"ok={r['ok']} codes={codes} · {he}"


@check("DGO-27 · memory is judged on AVAILABLE, not on total")
def c_available_not_total():
    # 16 GB total, nothing free: the shape of the machine this deployment actually runs on.
    r = admission.check(machine(mem_total_mb=16000, mem_avail_mb=300), [app("plane", "2G", "1.0")])
    ok = (not r["ok"] and any(p["code"] == "memory" for p in r["problems"]))
    return ok, f"total=16.0GB available=300MB → ok={r['ok']} ({r['summary']})"


@check("DGO-27 · a busy destination refuses on load PER CORE, not on core count")
def c_cpu():
    busy = admission.check(machine(ncpu=2, load1=6.0), [app("x", "128M")])
    idle = admission.check(machine(ncpu=16, load1=6.0), [app("x", "128M")])
    ok = (not busy["ok"] and any(p["code"] == "cpu" for p in busy["problems"]) and idle["ok"])
    return ok, (f"2 cores @6.00 → {[p['code'] for p in busy['problems']]}; "
                f"16 cores @6.00 → ok={idle['ok']} (load/cpu {idle['have']['load_per_cpu']})")


@check("DGO-27 · a full disk refuses BEFORE anything is pulled")
def c_disk():
    r = admission.check(machine(disk_avail_mb=1200), [app("x", "128M")])
    he = next((p["he"] for p in r["problems"] if p["code"] == "disk"), "")
    ok = not r["ok"] and "4.0GB" in he and "1.2GB" in he
    return ok, f"ok={r['ok']} · {he}"


@check("DGO-27 · an unprobed machine is refused, never assumed")
def c_unprobed():
    r = admission.check({"hostname": "p", "ncpu": 4, "load": "", "memory": {}, "disk": {}}, [app("x")])
    codes = [p["code"] for p in r["problems"]]
    return (not r["ok"] and codes == ["unprobed"]), f"codes={codes} · {r['summary']}"


@check("DGO-27 · a machine that could not be reached is refused with its reason")
def c_unreachable():
    r = admission.check_machine({"error": "TimeoutError"}, [app("x")])
    return (not r["ok"] and r["problems"][0]["code"] == "unreachable"), r["summary"]


@check("DGO-27 · an empty placement is refused")
def c_empty():
    r = admission.check(machine(), [])
    return (not r["ok"] and [p["code"] for p in r["problems"]] == ["empty"]), r["summary"]


@check("DGO-27 · the headroom makes a machine sized exactly to the limit refuse")
def c_headroom_bites():
    # 1000 MiB app on a machine with exactly 1000 MiB free: within the limit, over the margin.
    r = admission.check(machine(mem_avail_mb=1000), [app("x", "1000M")])
    ok = not r["ok"] and any(p["code"] == "memory" for p in r["problems"])
    return ok, f"1000MB free / 1000MB asked ({r['limits']['mem_headroom_pct']:.0f}% margin) → ok={r['ok']}"


@check("DGO-27 · every threshold is overridable, and the override is what is applied")
def c_overrides():
    low = machine(mem_avail_mb=500, disk_avail_mb=100, ncpu=1, load1=9.0)
    strict = admission.check(low, [app("x", "100M")])
    lax = admission.check(low, [app("x", "100M")], min_free_mb=0, mem_headroom_pct=0,
                          max_load_per_cpu=99)
    ok = (not strict["ok"] and lax["ok"]
          and {p["code"] for p in strict["problems"]} == {"cpu", "disk"})
    return ok, f"strict={[p['code'] for p in strict['problems']]} lax_ok={lax['ok']}"


@check("DGO-27 · sizes are read the way Docker writes them")
def c_units():
    cases = {"160M": 160.0, "1G": 1024.0, "512MiB": 512.0, "0.5G": 512.0, "2g": 2048.0,
             512: 512.0, "512": 512.0, "": 0.0, None: 0.0, "lots": 0.0}
    bad = {k: (admission.mib(k), v) for k, v in cases.items() if admission.mib(k) != v}
    return (not bad), (f"{len(cases)} spellings, {len(bad)} wrong" if bad else
                       f"all {len(cases)} spellings parse (160M, 1G, 512MiB, 0.5G, 2g, 512)")


@check("DGO-27 · need() sums the apps' OWN declarations, not a table kept beside them")
def c_need_from_apps():
    n = admission.need([app("a", "300M", "0.5"), app("b", "1G", "1.5"), {"id": "c"}])
    ok = n == {"memory_mb": 1324.0, "cpus": 2.0, "apps": 3}
    return ok, f"need={n}"


@check("DGO-27 · the load average is read out of computers' own spelling")
def c_load():
    ok = (admission.load_1("1.63 1.92 2.55") == 1.63 and admission.load_1("") == 0.0
          and admission.load_1(2.5) == 2.5)
    return ok, f"'1.63 1.92 2.55' → {admission.load_1('1.63 1.92 2.55')}"


@check("DGO-27 · the verdict on a real 15 GB / portable-machine record")
def c_portable():
    """The machine this work is FOR (192.168.16.103, ~15 GB): it must admit browser42 and refuse a
    placement that would not fit — the two halves of the same arithmetic."""
    m = machine(ncpu=4, load1=1.2, mem_total_mb=15000, mem_avail_mb=11000, disk_avail_mb=120000)
    small = admission.check(m, [app("browser42", "900M", "1.0")])
    huge = admission.check(m, [app("indox", "12G", "4.0")])
    ok = small["ok"] and not huge["ok"] and huge["problems"][0]["code"] == "memory"
    return ok, f"browser42 → {small['ok']}; indox 12GB → {huge['summary']}"


@check("DGO-407 · an office in a VM has room only if its HOST has, and the sentence says whose memory")
def c_host():
    """The VM's own figure approved everything on 2026-10-06 while its host had 275 MB free. A host
    that reports is judged; one that does not is not held against the office."""
    gib = 1024 * 1024 * 1024
    roomy_vm = dict(mem_total_mb=9950, mem_avail_mb=3700)
    starved = admission.check(machine(**roomy_vm, host={"mem_total": 16 * gib, "mem_free": 275 * 1024 * 1024}),
                              [app("drive", "256M")])
    healthy = admission.check(machine(**roomy_vm, host={"mem_total": 16 * gib, "mem_free": 5 * gib}),
                              [app("drive", "256M")])
    silent = admission.check(machine(**roomy_vm), [app("drive", "256M")])
    codes = [p["code"] for p in starved["problems"]]
    ok = (codes == ["host_memory"] and "275MB" in starved["summary"] and "16.0GB" in starved["summary"]
          and healthy["ok"] and silent["ok"] and silent["have"]["host_free_mb"] is None)
    return ok, f"host at 275MB → {starved['summary'][:90]}… · host at 5GB → {healthy['ok']} · no report → {silent['ok']}"


def main() -> int:
    failed = 0
    for fn in CHECKS:
        try:
            ok, measured = fn()
        except Exception as e:  # noqa: BLE001 — a raising check is a failing check, not a crash
            ok, measured = False, f"{type(e).__name__}: {e}"
        print(f"  {'PASS' if ok else 'FAIL'}  {fn._check_name}\n        {measured}")
        failed += 0 if ok else 1
    print(f"\n{'PASS' if not failed else 'FAIL'} — {len(CHECKS) - failed}/{len(CHECKS)} checks")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
