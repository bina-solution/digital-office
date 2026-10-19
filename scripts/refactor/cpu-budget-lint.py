#!/usr/bin/env python3
"""cpu-budget-lint — gate G65: declared CPU caps must fit the machine they run on.

    python3 scripts/refactor/cpu-budget-lint.py [--profile ci-small] [--verbose] [--render OUT]
    <id service lines> | python3 scripts/refactor/cpu-budget-lint.py --apply PLAN   (lib.sh, after `up`)

The CPU twin of G30. G30 exists because memory caps are decoration on one Docker host (the OOM
killer fires first). CPU caps are the opposite: the kernel enforces every `deploy.resources.limits.cpus`
as a CFS quota, so a declared sum far above the host is not a capacity plan that never bites — it
is a promise the scheduler tries to keep for every container at once.

Measured 2026-09-30 on the 4-vCPU macOS engine: 57 capped services declared 47.4 vCPU (11.9x).
Every container contended at once — CPU pressure 95%, load 145 on 4 cores, health probes overrunning
their timeouts, 12 containers flapping "unhealthy", containerd event delivery timing out — while every
agent was idle. Nothing was runaway; the caps simply let 47 vCPU of demand queue on 4.

Three things, one owner:
  * the CHECK: sum of caps over the ENABLED apps <= host_cpus x cpu_overcommit, both declared beside
    host_mem / mem_overcommit in platform/profiles/perf-profiles.yml. Overcommit is legitimate
    (services are not all hot at once); the ratio is a number someone chose.
  * the PLAN (`--render`): every enabled service's cap scaled by budget/declared_sum (never up,
    floor 0.1 so no service is starved) — scripts/perf-profile-apply writes it to
    .generated/cpu-budget.yml. No compose file is edited by hand.
  * the APPLY (`--apply`): the plan told to the KERNEL — `docker update --cpus` on every running
    container whose quota is not the plan's. lib.sh runs it after every `up`.

WHY THE SCALE IS NOT IN THE COMPOSE CONFIGURATION ANY MORE. It was: the plan was a compose overlay,
merged last. But the scale is budget/sum-over-EVERY-enabled-app, a cap is part of a container's
config hash, and so the scale was part of every container's identity: switching one app on moved
the cap of 24 of 26 capped services, and the next bring-up re-created them — the edge, two
databases, the sign-in — for an app that had nothing to do with them (measured on hp-laptop
2026-10-06, issues/a-containers-configuration-depends-on-who-asks-and-on-who-else-runs.yaml). A cap
is enforced by the kernel and must follow the running set; that makes it runtime state OF THE SET.
What stays in the overlay's `services:` is the one thing creation itself needs: a cap this machine
cannot give at all (more cores than it has — docker refuses to create such a container) is lowered
to the machine's cores. That is a function of the service and the machine, never of its neighbours.

The sum is computed from the app compose files, not from `dc config`, for the same reason G30 does:
the gate must run on a checkout with no engine. A reservation is a floor, not a cap, and is ignored.
Exit 0 = within budget. Exit 1 = over budget, or the profile has no CPU envelope.
"""
import os
import pathlib
import re
import subprocess
import sys

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "refactor"))
sys.path.insert(0, str(REPO / "platform" / "manager"))
import reconcile  # noqa: E402 — the one reader of the state file
from importlib import import_module  # noqa: E402

_g30 = import_module("memory-budget-lint")  # read_env, enabled_apps: one reading of "enabled"
ROOTS = ("apps", "platform-base")
FLOOR = 0.1                      # below this a service cannot even answer its health probe
PLAN = "x-cpu-budget"            # the plan's key in the rendered file: an extension field, so compose reads past it
ENVREF = re.compile(r"^\$\{(\w+)(?::?-(.*?))?\}$")


def to_cpus(v, env):
    """A compose `cpus` value as a float, resolving ${VAR:-default} against .env then the default."""
    if v is None:
        return None
    s = str(v).strip().strip("'\"")
    m = ENVREF.match(s)
    if m:
        s = env.get(m.group(1)) or (m.group(2) or "")
    try:
        return float(s)
    except ValueError:
        return None


def declared(env, enabled):
    """[(cpus, service, app, raw)] for every capped service of every enabled app."""
    rows = []
    for root in ROOTS:
        for app_dir in sorted((REPO / root).iterdir()):
            cf = app_dir / "docker-compose.yml"
            if not cf.exists() or app_dir.name not in enabled:
                continue
            cfg = yaml.safe_load(cf.read_text(encoding="utf-8")) or {}
            for sname, svc in (cfg.get("services") or {}).items():
                if not isinstance(svc, dict):
                    continue
                raw = (((svc.get("deploy") or {}).get("resources") or {}).get("limits") or {}).get("cpus")
                c = to_cpus(raw, env)
                if c:
                    rows.append((c, sname, app_dir.name, str(raw)))
    return rows


def render_overlay(rows, budget, path, cores=None):
    """Write the plan. Scale = min(1, budget/sum): caps only ever go DOWN.

    Two parts, read by two readers (see the module docstring for why they are apart):
      `services:`  what a container is CREATED with when its own cap is more than this machine has
                   cores — merged by compose (reconcile.compose_files), and usually empty;
      PLAN         what every enabled cap is at this scale — applied to the running set (`apply`).
    """
    cores = float(cores if cores is not None else os.cpu_count() or 0)
    total = sum(c for c, *_ in rows)
    scale = min(1.0, budget / total) if total else 1.0
    fits = lambda c: min(c, cores) if cores else c                      # noqa: E731
    created = {s: {"deploy": {"resources": {"limits": {"cpus": f"{cores:g}"}}}} for c, s, *_ in rows if fits(c) < c}
    plan = {s: max(FLOOR, round(fits(c) * scale, 2)) for c, s, *_ in rows}
    head = ("# GENERATED by scripts/perf-profile-apply — do not edit. Gate G65 (cpu-budget-lint.py).\n"
            f"# Enabled services declare {total:.2f} vCPU of caps; the profile's budget is {budget:.2f}\n"
            f"# (host_cpus x cpu_overcommit), so every cap is scaled by {scale:.3f} (floor {FLOOR}).\n"
            f"# `{PLAN}` is that scale per service, told to the kernel after every `up` (docker update) —\n"
            "# never part of a container's configuration. `services:` is merged LAST by\n"
            "# reconcile.compose_files() and holds only a cap this machine has too few cores to create.\n")
    body = yaml.safe_dump({"services": created, PLAN: plan}, sort_keys=True, allow_unicode=True)
    pathlib.Path(path).write_text(head + body, encoding="utf-8", newline="\n")
    return scale, sum(1 for c, s, *_ in rows if plan[s] < c)


def apply(path, running, docker=("docker",), dry=False):
    """Tell the kernel the plan: `running` is the `<container id> <service>` lines of this office's
    containers; each whose quota is not its service's planned one gets it. Returns what was changed
    — or, with `dry`, what would be (scripts/config-by-caller.sh asks exactly that).

    A container compose has just created holds its DECLARED cap until this runs — seconds at a
    higher cap, on the way to the right one. A restart keeps what was set; only a re-creation loses
    it, and a re-creation is an `up`, which is followed by this.
    """
    plan = (yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}).get(PLAN) or {}
    want = {cid: float(plan[svc]) for cid, svc in (ln.split()[:2] for ln in running if len(ln.split()) >= 2)
            if svc in plan}
    if not want:
        return []
    shown = subprocess.run([*docker, "inspect", "--format", "{{.Id}} {{.HostConfig.NanoCpus}} {{.Name}}", *want],
                           capture_output=True, text=True).stdout
    changed = []
    for full, nano, name in (ln.split() for ln in shown.splitlines() if len(ln.split()) == 3):
        cpus = next(v for cid, v in want.items() if full.startswith(cid))
        if int(nano) != round(cpus * 1e9):
            ok = dry or subprocess.run([*docker, "update", "--cpus", f"{cpus:g}", full],
                                       capture_output=True, text=True).returncode == 0
            changed.append((name.lstrip("/"), int(nano) / 1e9, cpus, ok))
    return changed


def main():
    if "--apply" in sys.argv:
        changed = apply(sys.argv[sys.argv.index("--apply") + 1], sys.stdin.read().splitlines(),
                        dry="--dry-run" in sys.argv)
        for name, was, now, ok in changed:
            print(f"cpu: {name} {was:g} -> {now:g}" + ("" if ok else " — REFUSED by the engine"))
        return 0 if all(ok for *_, ok in changed) else 1
    verbose = "--verbose" in sys.argv
    env = _g30.read_env()
    state = reconcile.load_state()
    enabled = _g30.enabled_apps(state)
    profiles = yaml.safe_load((REPO / "platform/profiles/perf-profiles.yml").read_text(encoding="utf-8")) or {}
    prof = (sys.argv[sys.argv.index("--profile") + 1] if "--profile" in sys.argv
            else env.get("PERFORMANCE_PROFILE") or state.get("performance_profile") or "prod")
    if prof not in profiles:
        print(f"G65 FAIL — unknown performance profile {prof!r} (known: {', '.join(sorted(profiles))})")
        return 1
    p = profiles[prof] or {}
    host_cpus, ratio = p.get("host_cpus"), p.get("cpu_overcommit")
    if not host_cpus or not ratio:
        print(f"G65 FAIL — profile {prof!r} declares no CPU envelope (host_cpus + cpu_overcommit).")
        print("  Add both beside host_mem / mem_overcommit in platform/profiles/perf-profiles.yml.")
        return 1
    budget = float(host_cpus) * float(ratio)
    rows = declared(env, enabled)
    total = sum(c for c, *_ in rows)
    print(f"G65 — profile {prof!r}: host_cpus {host_cpus} x{float(ratio):g} = {budget:g} vCPU budget")
    print(f"      {len(enabled)} enabled app(s), {len(rows)} capped service(s), declared sum {total:.2f} vCPU")
    if verbose:
        for c, sname, app, raw in sorted(rows, reverse=True)[:15]:
            print(f"        {c:5.2f}  {app}/{sname:30} {raw}")
    if "--render" in sys.argv:
        out = sys.argv[sys.argv.index("--render") + 1]
        scale, n = render_overlay(rows, budget, out)
        print(f"      rendered {out}: {n} cap(s) scaled by {scale:.3f}")
        return 0        # the render IS the remedy; a rendered estate is within budget by construction
    # The rendered plan IS the remedy: when .generated/cpu-budget.yml exists and was rendered for
    # this profile against this declared sum, every `up` is followed by its application to the
    # running containers, and the check passes on it. A stale plan (different sum) does not count.
    ov = REPO / ".generated" / "cpu-budget.yml"
    if total > budget and ov.exists():
        head = ov.read_text(encoding="utf-8")[:400]
        if f"declare {total:.2f} vCPU" in head and f"budget is {budget:.2f}" in head:
            print(f"G65 PASS — over budget on paper ({total:.2f} > {budget:g}), but the rendered plan "
                  f".generated/cpu-budget.yml scales the enabled caps to fit (applied after every `up`).")
            return 0
        print("      (.generated/cpu-budget.yml is STALE — rendered for another sum/profile; re-run perf-profile-apply)")
    if total > budget:
        print(f"G65 FAIL — declared caps exceed the budget by {total - budget:.2f} vCPU "
              f"({total / budget:.1f}x). Run `python3 scripts/perf-profile-apply` to render the")
        print("  scaling plan, or raise `cpu_overcommit` for this profile and say why.")
        return 1
    print("G65 PASS — declared CPU caps fit the profile's machine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
