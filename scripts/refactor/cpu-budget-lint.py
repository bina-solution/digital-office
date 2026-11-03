#!/usr/bin/env python3
"""cpu-budget-lint — gate G65: declared CPU caps must fit the machine they run on.

    python3 scripts/refactor/cpu-budget-lint.py [--profile ci-small] [--verbose] [--render OUT]
    <id service lines> | python3 scripts/refactor/cpu-budget-lint.py --apply PLAN   (lib.sh, after `up`)
    python3 scripts/refactor/cpu-budget-lint.py --self-test    (the render's native and emulated branches)

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
    .generated/cpu-budget.yml. No compose file is edited by hand. On an emulated CPU no service is
    capped at all instead (render_overlay says why).
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
On an emulated CPU it holds every capped service instead, uncapped (`cpus: '0'`): a function of the
machine alone, and not of how many cores it boots with.

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
    """[(cpus, service, app, raw, floor)] for every capped service of every enabled app.

    `floor` is the service's OWN declared reservation (`deploy.resources.reservations.cpus`) —
    compose's word for "at least this much", and the one number in this file a service gets to say
    about itself. It is never above the service's own cap: a reservation larger than the limit is
    the limit. See `scale_for` for why a floor matters (DGO-523)."""
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
                res = (svc.get("deploy") or {}).get("resources") or {}
                raw = (res.get("limits") or {}).get("cpus")
                c = to_cpus(raw, env)
                if c:
                    floor = to_cpus((res.get("reservations") or {}).get("cpus"), env) or 0.0
                    rows.append((c, sname, app_dir.name, str(raw), min(floor, c)))
    return rows


def scale_for(rows, budget):
    """The largest scale in [0,1] whose PLAN fits `budget` while every declared floor holds.

    Caps-only scaling used to be `budget / sum(caps)`, applied to every service alike — which is what
    starved the one process every request passes through: the console declares 0.5 for itself
    (its own compose limit), the profile's 0.612 handed it 0.31, and the kernel held it back in more
    than a third of the periods while it answered pages (DGO-523, measured 2026-10-10). A service
    that declares a floor is a service whose author said "below this it cannot do its job", so the
    floor is spent FIRST and the rest of the budget is scaled across what remains. The result still
    fits: the plan's sum is what the budget is for.

    Monotone in `scale`, so a bisection answers it exactly enough for two decimals of CPU."""
    def plan_total(s):
        return sum(max(row[4], row[0] * s) for row in rows)
    if plan_total(1.0) <= budget:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if plan_total(mid) <= budget:
            lo = mid
        else:
            hi = mid
    return lo


def emulated():
    """True on a machine whose CPU is emulated: QEMU without KVM (TCG), the way the Android app's
    engine runs the office on a phone (DGO-1084). `systemd-detect-virt --vm` names it `qemu`; a KVM
    guest is `kvm`, the Mac's engine (vz) `apple`, WSL2 and GitHub's runners `microsoft`, bare metal
    `none`. QEMU under Apple's HVF (Lima's `vmType: qemu`, UTM) says `qemu` too — no office runs one."""
    try:
        r = subprocess.run(["systemd-detect-virt", "--vm"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.stdout.strip() == "qemu"


def render_overlay(rows, budget, path, cores=None, slow=None):
    """Write the plan. Scale = min(1, budget/sum): caps only ever go DOWN.

    Two parts, read by two readers (see the module docstring for why they are apart):
      `services:`  what a container is CREATED with when its own cap is more than this machine has
                   cores — merged by compose (reconcile.compose_files), and usually empty;
      PLAN         what every enabled cap is at this scale — applied to the running set (`apply`).

    On an emulated CPU (`slow`, default `emulated()`) no service is capped: every capped one is created
    with `cpus: '0'` (compose's no limit, as apitools' default) and none is in the plan. A cap is a
    share of a NATIVE core, and an emulated one does about a twentieth of its work: docker-socket-proxy's
    0.10 and authentik-postgres's 0.5 starved the phone's first start (authentik 50 minutes, then the
    proxy's probe failed; android-guest run 41249591722). The machine is the office's alone, so the
    scheduler's fair share is what is left to divide it. Not the machine's cores: the phone boots its
    machine with as many as it spares that day, and a container created above them would not start.
    """
    if emulated() if slow is None else slow:
        return _render_uncapped(rows, budget, path)
    cores = float(cores if cores is not None else os.cpu_count() or 0)
    total = sum(c for c, *_ in rows)
    # `fits` FIRST: a cap this machine cannot create at all is lowered before the budget is divided
    # (docker refuses to create a container capped above the host's cores), and the last field keeps
    # the fact that creation itself needs it — that is what the overlay's `services:` is for.
    capped = []
    for c, sname, app, raw, floor in rows:
        fits = min(c, cores) if cores else c
        capped.append((fits, sname, app, raw, min(floor, fits), fits < c))
    scale = scale_for(capped, budget)
    created = {s: {"deploy": {"resources": {"limits": {"cpus": f"{cores:g}"}}}}
               for _c, s, _a, _r, _f, over in capped if over}
    plan = {s: max(FLOOR, round(c * scale, 2), round(floor, 2)) for c, s, _, _, floor, _o in capped}
    held = [(s, floor) for c, s, _, _, floor, _o in capped if floor and c * scale < floor]
    head = ("# GENERATED by scripts/perf-profile-apply — do not edit. Gate G65 (cpu-budget-lint.py).\n"
            f"# Enabled services declare {total:.2f} vCPU of caps; the profile's budget is {budget:.2f}\n"
            f"# (host_cpus x cpu_overcommit), so the caps are scaled by {scale:.3f} (floor {FLOOR}).\n"
            + (f"# {len(held)} service(s) declare a floor of their own (reservations.cpus) and are held AT\n"
               f"# it, the budget taken out of the rest first: "
               + ", ".join(f"{s} {f:g}" for s, f in sorted(held)) + ".\n" if held else "")
            + f"# The plan's own sum is {sum(plan.values()):.2f} vCPU.\n"
            f"# `{PLAN}` is that scale per service, told to the kernel after every `up` (docker update) —\n"
            "# never part of a container's configuration. `services:` is merged LAST by\n"
            "# reconcile.compose_files() and holds only a cap this machine has too few cores to create.\n")
    body = yaml.safe_dump({"services": created, PLAN: plan}, sort_keys=True, allow_unicode=True)
    # The writer makes its own directory, and only now: the state has been read (`main`), so a first
    # run has its platform.state.yaml before `.generated/` exists — which `reconcile.ensure_state`
    # reads as "this checkout has compiled before" (DGO-1023).
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(path).write_text(head + body, encoding="utf-8", newline="\n")
    return scale, sum(1 for c, s, *_ in capped if plan[s] < c)


EMULATED = "this machine's CPU is emulated"   # the uncapped plan's header says it; G65 reads it


def _render_uncapped(rows, budget, path):
    """render_overlay on an emulated CPU: every capped service created uncapped, and no plan."""
    total = sum(c for c, *_ in rows)
    # one dict each: a shared one would be written as YAML anchors and aliases
    created = {s: {"deploy": {"resources": {"limits": {"cpus": "0"}}}} for _c, s, *_ in rows}
    # the first two lines as render_overlay writes them: G65 reads them to tell a current plan
    head = ("# GENERATED by scripts/perf-profile-apply — do not edit. Gate G65 (cpu-budget-lint.py).\n"
            f"# Enabled services declare {total:.2f} vCPU of caps; the profile's budget is {budget:.2f}\n"
            f"# — and {EMULATED} (systemd-detect-virt: qemu), so none is capped: a cap\n"
            "# is a share of a native core, and an emulated one does about a twentieth of its work\n"
            "# (render_overlay). `services:` creates every capped service with cpus '0' (no limit); the\n"
            "# plan tells the kernel nothing.\n")
    body = yaml.safe_dump({"services": created, PLAN: {}}, sort_keys=True, allow_unicode=True)
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(path).write_text(head + body, encoding="utf-8", newline="\n")
    print(f"      emulated CPU: {len(rows)} cap(s) lifted")
    return 1.0, 0


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


def self_test():
    """--self-test: the render's two branches, on rows made up here. The gates run where
    systemd-detect-virt is absent or names no emulator, so CI never takes the emulated branch itself."""
    import tempfile
    rows = [(0.10, "proxy", "traefik", "0.10", 0.01), (0.5, "pg", "authentik", "0.5", 0.25), (8.0, "big", "x", "8", 0.0)]
    total = sum(c for c, *_ in rows)
    checks = []
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "plan.yml"
        render_overlay(rows, 2.0, p, cores=4, slow=False)
        y = yaml.safe_load(p.read_text(encoding="utf-8"))
        checks.append(("native: only a cap above the cores is created at the cores",
                       y["services"] == {"big": {"deploy": {"resources": {"limits": {"cpus": "4"}}}}}))
        checks.append(("native: over budget, the plan scales the caps down", y[PLAN]["big"] < 4))
        checks.append(("native: a declared floor holds", y[PLAN]["pg"] >= 0.25))
        render_overlay(rows, 2.0, p, cores=4, slow=True)
        txt = p.read_text(encoding="utf-8")
        y = yaml.safe_load(txt)
        checks.append(("emulated: every capped service is created uncapped (cpus '0')",
                       {s: v["deploy"]["resources"]["limits"]["cpus"] for s, v in y["services"].items()}
                       == {"proxy": "0", "pg": "0", "big": "0"}))
        checks.append(("emulated: the plan tells the kernel nothing", y[PLAN] == {}))
        render_overlay(rows, 2.0, pathlib.Path(d) / "two.yml", cores=2, slow=True)
        checks.append(("emulated: the render does not depend on the machine's cores",
                       (pathlib.Path(d) / "two.yml").read_text(encoding="utf-8") == txt))
        checks.append(("emulated: no YAML anchors or aliases", "&id" not in txt and "*id" not in txt))
        checks.append(("emulated: G65 still reads the plan as current, and as the emulated one",
                       f"declare {total:.2f} vCPU" in txt[:400] and "budget is 2.00" in txt[:400] and EMULATED in txt[:400]))
    real = subprocess.run
    for said, want in (("qemu\n", True), ("kvm\n", False), ("none\n", False), (None, False)):
        def fake(*a, said=said, **k):
            if said is None:
                raise FileNotFoundError("systemd-detect-virt")
            return subprocess.CompletedProcess(a, 0, stdout=said, stderr="")
        subprocess.run = fake
        try:
            got = emulated()
        finally:
            subprocess.run = real
        checks.append((f"emulated() is {want} when systemd-detect-virt says {said.strip() if said else 'nothing (absent)'}",
                       got is want))
    for name, ok in checks:
        print(("  ok    " if ok else "  FAIL  ") + name)
    good = sum(1 for _, ok in checks if ok)
    print(f"cpu-budget-lint self-test: {good}/{len(checks)} passed")
    return 0 if good == len(checks) else 1


def main():
    if "--self-test" in sys.argv:
        return self_test()
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
    # The envelope is a claim about THIS machine. A profile whose host_cpus is more than the box has
    # renders a plan sized for a machine that is not there: fireplace (2 vCPU) ran `ci-small`
    # (host_cpus 4, budget 16) for weeks, and the recorder's cap came out at 0.48 of a core
    # (issues/fireplace-perf-profile-declares-four-cores-on-a-two-core-box.yaml, 2026-10-26). Said,
    # not failed: CI renders on runners of every size, and the selector is where the choice is made.
    machine = os.cpu_count() or 0
    if machine and float(host_cpus) > machine:
        print(f"G65 WARNING — profile {prof!r} declares host_cpus {host_cpus}, this machine has {machine}: "
              f"the budget is {budget / machine:.1f}x the box. `python3 platform/manager/select-profile.py "
              f"--explain` names the profile whose envelope fits; PERFORMANCE_PROFILE in .env adopts it.")
    print(f"      {len(enabled)} enabled app(s), {len(rows)} capped service(s), declared sum {total:.2f} vCPU")
    if verbose:
        for c, sname, app, raw, _floor in sorted(rows, reverse=True)[:15]:
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
        if f"declare {total:.2f} vCPU" in head and f"budget is {budget:.2f}" in head and EMULATED in head:
            print(f"G65 PASS — over budget on paper ({total:.2f} > {budget:g}), and {EMULATED}: the "
                  "rendered plan .generated/cpu-budget.yml caps no service.")
            return 0
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
