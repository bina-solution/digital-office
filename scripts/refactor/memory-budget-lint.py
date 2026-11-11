#!/usr/bin/env python3
"""memory-budget-lint — gate G30: declared memory limits must fit the machine they run on.

    python3 scripts/refactor/memory-budget-lint.py [--profile prod] [--verbose] [--strict]

The enabled render declares far more memory than any host it targets has. Nobody chose that number
and nobody could see it: every limit is a literal in one app's compose, and no view sums them.

The caps are not doing what they look like they are doing. On a single Docker host an over-subscribed
`deploy.resources.limits.memory` provides **no protection** — the host OOM-killer fires long before
the cgroup caps do, and it picks its own victim. So the numbers read as a capacity plan while
behaving like decoration. The same declarations under swarm or k8s stop being decoration and become
hard scheduling failures: nothing would place.

Overcommit is legitimate — services are not all hot at once, and `packaging/OPTIMISATION.md` measures
actual usage far below the declared sum. This gate does not demand sum <= host. It demands the
overcommit be a RATIO SOMEONE CHOSE, declared next to the machine envelope it applies to, so it
cannot silently grow again.

`host_mem` per profile lives in platform/profiles/perf-profiles.yml. `reservations` are not limits
and are never counted. A service with no limit at all is reported, because an uncapped service is an
undeclared decision, not a small one.

TWO PLACES DECLARE A MEMORY BUDGET, AND NOTHING COMPARED THEM. An app's app.json carries
`resources.memory` — the number every human-facing surface shows and `app-management`'s room check
reads — while the number actually enforced is a literal in that app's docker-compose.yml under
`deploy.resources.limits.memory`. Measured 2026-11-05: hello-bina declared 64M in its manifest and its
compose declared nothing at all, so the enforced limit was the whole host (docker stats read
`13.35MiB / 7.766GiB`); forward-auth — the office's sign-in — enforced nothing either and declared
nothing; and four more enabled apps declare a figure their compose does not reach (`machine` 384M vs
640M, which its own brief admits, `bina-ds` 1g vs 2g, `n8n` 2g vs the 20.5G its eight services sum to,
`apitools` 4g vs 5.5G). The pair is compared
HERE, per app: the app is the unit of declaration, and the figure counts as honoured when either the
app's OWN service or the sum of its services enforces exactly it — both conventions are in the tree
(`sites` declares its own container, `meet` its total) and neither is drift. A manifest declaring one
figure beside a compose that reaches it no way is reported with both numbers.

It REPORTS (like the uncapped list) and does not fail by default: the exit code stays the budget's,
and the mismatches that predate the check are not retroactively made the gate's problem. `--strict`
promotes them to failures — that is the switch for when the tree has been brought level.

CPU caps are deliberately NOT compared: `cpu-budget-lint.py` (G65) OWNS them and scales the enforced
figure to the machine at render time, so a static app.json-vs-compose equality there would fail on a
correct tree.

Exit 0 = the sum is within budget. Exit 1 = over budget, or a profile has no declared envelope
(with `--strict`: also a declared memory its compose does not reach).
"""
import sys, os, re, json, pathlib

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "platform" / "manager"))
import reconcile  # noqa: E402 — the one reader of the state file
ROOTS = ("apps", "platform-base")
DEFAULT_RATIO = 3.0          # overcommit is legitimate; 5x is not

SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmg])?i?b?\s*$", re.I)
UNIT = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}
# ${VAR:-default} / ${VAR-default} / ${VAR}
ENVREF = re.compile(r"^\$\{(\w+)(?::?-(.*?))?\}$")


def to_bytes(v, env):
    """Parse a compose memory value, resolving ${VAR:-default} against .env then the inline default."""
    if v is None:
        return None
    s = str(v).strip()
    m = ENVREF.match(s)
    if m:
        name, default = m.group(1), m.group(2)
        s = env.get(name) or default or ""
        if not s:
            return None
    m = SIZE.match(s)
    if not m:
        return None
    return int(float(m.group(1)) * UNIT[(m.group(2) or "").lower()])


def read_env():
    env, p = {}, REPO / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def enabled_apps(state):
    """Apps the platform should actually RUN — the SAME reading the compiler uses.

    This used to accept only `enabled: true` / `true`, while `bbox apps enable` writes
    `{state: enabled, by: cli}` and the compiler (reconcile.disposition) treats `state:` as
    authoritative. So every app enabled the supported way was INVISIBLE to this gate: on 2026-09-23
    it reported "19 enabled apps, declared sum 41.0 GiB" for a render that actually starts 24, and
    the six it could not see included `computers`, `git`, `sites` and `sites-render` — the four
    biggest additions of that week. A budget check that cannot see the thing being added is not a
    budget check; it reads green while the number it exists to bound grows.

    `archived` is deliberately NOT enabled: archived reclaims the containers and images.

    It is the compiler's reading now by construction — a copy of `reconcile.disposition` is how the
    two drifted in the first place.
    """
    return {k for k, v in (state.get("apps") or {}).items() if reconcile.disposition(v) == "enabled"}


def human(b):
    return f"{b / 1024 ** 3:.1f} GiB" if b >= 1024 ** 3 else f"{b / 1024 ** 2:.0f} MiB"


def declared_mismatches(enabled, env):
    """Enabled apps whose app.json `resources.memory` is not what their own compose enforces.

    Returns [(app, declared_as_written, declared_bytes, own_service_bytes, all_services_bytes, n)].
    TWO CONVENTIONS ARE IN THE TREE and neither is drift, so the declared figure counts as honoured
    when EITHER reaches it exactly: the app's own service (the one named like the app — `sites`
    declares 320M and its `sites` service enforces 320M, beside a renderer that is another service),
    or the sum of every service in the app's compose (`meet` declares 3472M and its seven services
    sum to exactly that — an app-level figure can only mean the app's total). A finding is therefore
    a figure NEITHER reaches. An app whose manifest says nothing is not asked here: an uncapped
    service is the list above's finding, not this one.
    """
    out = []
    for root in ROOTS:
        for app_dir in sorted((REPO / root).iterdir()):
            if app_dir.name not in enabled:
                continue
            af, cf = app_dir / "app.json", app_dir / "docker-compose.yml"
            if not af.exists() or not cf.exists():
                continue
            try:
                app = json.loads(af.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # a manifest that does not parse is manifest-lint.py's (G73) finding
            raw = ((app.get("resources") or {}) if isinstance(app, dict) else {}).get("memory")
            declared = to_bytes(raw, env)
            if declared is None:
                continue
            cfg = yaml.safe_load(cf.read_text(encoding="utf-8")) or {}
            limits = {}
            for sname, svc in (cfg.get("services") or {}).items():
                if not isinstance(svc, dict):
                    continue
                limits[sname] = to_bytes((((svc.get("deploy") or {}).get("resources") or {})
                                          .get("limits") or {}).get("memory"), env) or 0
            own = limits.get(app_dir.name, 0)
            whole = sum(limits.values())
            if declared in (own, whole):
                continue
            out.append((app_dir.name, str(raw).strip(), declared, own, whole, len(limits)))
    return out


def main():
    verbose = "--verbose" in sys.argv
    strict = "--strict" in sys.argv
    env = read_env()

    state = reconcile.load_state()
    enabled = enabled_apps(state)

    profiles = yaml.safe_load(
        (REPO / "platform/profiles/perf-profiles.yml").read_text(encoding="utf-8")) or {}
    if "--profile" in sys.argv:
        prof = sys.argv[sys.argv.index("--profile") + 1]
    else:
        prof = env.get("PERFORMANCE_PROFILE") or state.get("performance_profile") or "prod"
    if prof not in profiles:
        print(f"G30 FAIL — unknown performance profile {prof!r} "
              f"(known: {', '.join(sorted(profiles))})")
        return 1

    host_mem = to_bytes((profiles[prof] or {}).get("host_mem"), env)
    if not host_mem:
        print(f"G30 FAIL — profile {prof!r} declares no `host_mem`.")
        print("  A memory budget cannot be checked against an undeclared machine. Add host_mem to")
        print("  platform/profiles/perf-profiles.yml — it is the envelope the profile already")
        print("  implies in prose ('4-core VPS', '8-core production'), just written down.")
        return 1

    ratio = float(env.get("MEMORY_BUDGET_RATIO") or
                  (profiles[prof] or {}).get("mem_overcommit") or DEFAULT_RATIO)
    budget = int(host_mem * ratio)

    total, capped, uncapped, rows = 0, 0, [], []
    for root in ROOTS:
        for app_dir in sorted((REPO / root).iterdir()):
            cf = app_dir / "docker-compose.yml"
            if not cf.exists() or app_dir.name not in enabled:
                continue
            cfg = yaml.safe_load(cf.read_text(encoding="utf-8")) or {}
            for sname, svc in (cfg.get("services") or {}).items():
                if not isinstance(svc, dict):
                    continue
                # limits ONLY — a reservation is a floor, not a cap, and counting it double-counts.
                lim = (((svc.get("deploy") or {}).get("resources") or {})
                       .get("limits") or {}).get("memory")
                b = to_bytes(lim, env)
                if b is None:
                    uncapped.append(f"{app_dir.name}/{sname}")
                else:
                    total += b
                    capped += 1
                    rows.append((b, f"{app_dir.name}/{sname}", str(lim)))

    gib = 1024 ** 3
    print(f"G30 — profile {prof!r}: host_mem {host_mem/gib:.1f} GiB x{ratio:g} "
          f"= {budget/gib:.1f} GiB budget")
    print(f"      {len(enabled)} enabled app(s), {capped} capped service(s), "
          f"declared sum {total/gib:.1f} GiB")

    if verbose:
        for b, name, raw in sorted(rows, reverse=True)[:15]:
            print(f"        {b/gib:6.2f} GiB  {name:34} {raw}")

    if uncapped:
        print(f"      {len(uncapped)} service(s) declare NO limit "
              f"(an uncapped service is an undeclared decision):")
        for u in uncapped:
            print(f"        {u}")

    rc = 0
    drift = declared_mismatches(enabled, env)
    if drift:
        print(f"      {len(drift)} app(s) declare a memory budget their compose does not enforce "
              f"(app.json `resources.memory` vs its own service, and vs all its services):")
        for name, raw, declared, own, whole, n in drift:
            own_s = human(own) if own else "NO limit"
            whole_s = human(whole) if whole else "NO limit"
            print(f"        {name:26} app.json {raw:>7} ({human(declared)}) · compose own service "
                  f"{own_s}, all {n} service(s) {whole_s}")
        if strict:
            rc = 1
            print("  -> --strict: a manifest's declared memory is not what its compose enforces.")
    if total > budget:
        print(f"G30 FAIL — declared limits exceed the budget by "
              f"{(total-budget)/gib:.1f} GiB.")
        print("  -> lower a limit, or raise `mem_overcommit` for this profile and say why.")
        print("     On one Docker host these caps do not protect anything (the host OOM-killer")
        print("     fires first); under swarm/k8s they become hard scheduling failures.")
        rc = 1
    else:
        print("G30 PASS — declared memory fits the chosen overcommit of the declared machine")

    rc = max(rc, peak_check())
    return rc


# ═════════════════════════════════════════════════════════════════════════════════════════════════
# G30b — OBSERVED PEAK vs PHYSICAL. The check that actually predicts this host falling over.
# ═════════════════════════════════════════════════════════════════════════════════════════════════
# Everything above lints DECLARED limits, which are ceilings nobody is obliged to reach. That number
# tells you what someone wrote down. It does not tell you whether the machine survives.
#
# What predicts failure here is the sum of what containers ACTUALLY reach against the memory the
# machine ACTUALLY has. Measured 2026-08-06 during a real pipeline run: peak sum 10363 MiB against
# 9950 MiB physical — over 100%. That is the honest explanation for why this host swaps, why
# MemAvailable collapses, and why the WSL distro was torn down 42 times in 24 hours.
#
# ── HOW TO READ THE NUMBER, because it is easy to over-claim ──────────────────────────────────────
# This is a RUNNING MAXIMUM PER CONTAINER, ACCUMULATED OVER TIME. It is NOT a simultaneous
# snapshot. Two containers whose peaks are recorded an hour apart both contribute in full, so a
# sum over 100% does NOT prove the stack needed that much at any single instant, and it is not a
# claim that the stack "needs 10.4 GiB at once".
#
# It is a WORST-CASE ENVELOPE: the memory the stack would require if every container hit its own
# high-water mark together. Treat >100% as "this configuration has no margin against a bad
# coincidence", not as "this is the current working set". The precise simultaneous figure would
# need synchronised sampling, which scripts/ops/peak-sampler.sh deliberately does not attempt —
# per-container maxima survive container restarts, and a synchronised snapshot would not.
def peak_check():
    peaks = REPO / "scripts" / "ops" / ".peak-sampler-state" / "peaks.tsv"
    if not peaks.exists() or peaks.stat().st_size == 0:
        print()
        print("G30b — observed peak vs physical: NOT VERIFIED (no sample on disk).")
        print("  Run `bash scripts/ops/peak-sampler.sh` during real load, then re-run this gate.")
        print("  Deliberately NOT a failure: absence of a sample is not evidence of a good one.")
        return 0

    # WHOSE sample is it. The file is one deployment's high-water marks, and every container in it is
    # named `<service>-<DEPLOYMENT_NAME>`. The copy in git was taken on 2026-08-06 on a deployment
    # called `owner-laptop`, and this check summed it against the memory of WHATEVER machine ran the
    # gate — a clean clone, a CI runner, another office — and failed all of them at "229%" for a
    # stack none of them runs. A sample says something only about the deployment it was taken on.
    name = read_env().get("DEPLOYMENT_NAME") or ""
    total_peak = 0
    rows, foreign = [], set()
    for line in peaks.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        try:
            p, l = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if not name or not parts[0].endswith("-" + name):
            foreign.add(parts[0].rsplit("-", 1)[-1] if "-" in parts[0] else parts[0])
            continue
        total_peak += p
        rows.append((p, l, parts[0]))
    if not rows:
        print()
        print("G30b — observed peak vs physical: NOT VERIFIED (the sample on disk is not this deployment's"
              f"{' — ' + repr(name) if name else ''}; it names {', '.join(sorted(foreign)[:3]) or 'nothing'}).")
        print("  Run `bash scripts/ops/peak-sampler.sh` during real load HERE, then re-run this gate.")
        return 0

    phys = 0
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                phys = int(line.split()[1]) // 1024
                break
    except OSError:
        pass
    if not phys:
        print("\nG30b — observed peak vs physical: NOT VERIFIED (cannot read MemTotal).")
        return 0

    pct = total_peak * 100 // phys
    print()
    print(f"G30b — observed peak sum {total_peak} MiB vs physical {phys} MiB = {pct}%")
    print("       (running max per container, accumulated over time — a worst-case envelope,")
    print("        NOT a simultaneous snapshot. See the note above this function.)")

    tight = [(p, l, n) for p, l, n in rows if l > 0 and p * 100 // l >= 80]
    if tight:
        print("       containers at >=80% of their own limit (raise these, do not cut them):")
        for p, l, n in sorted(tight, reverse=True):
            print(f"         {n:<42} {p} / {l} MiB ({p*100//l}%)")

    if pct >= 100:
        print(f"G30b FAIL — the stack's worst-case envelope ({pct}%) exceeds physical memory.")
        print("  There is no margin against every container peaking together. Reduce DEMAND")
        print("  (scripts/ops/quiet-mode.sh stops what is not on the document path) rather than")
        print("  lowering limits below measured peaks — that trades swap-death for OOM kills.")
        return 1
    print(f"G30b PASS — worst-case envelope {pct}% of physical.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
