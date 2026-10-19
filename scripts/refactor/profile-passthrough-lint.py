#!/usr/bin/env python3
"""profile-passthrough-lint — gate G57: every knob a profile sets must reach a container.

    python3 scripts/refactor/profile-passthrough-lint.py [--verbose]

WHY THIS GATE EXISTS
--------------------
On 2026-08-06 `platform/profiles/perf-profiles.yml` pinned `APITOOLS_MAX_CONCURRENT_PDF: 5`. The
value was written to `.env` correctly by `scripts/perf-profile-apply`. It appeared in `.env`. It
looked authoritative. It did nothing — because `apps/apitools/docker-compose.yml` never passed it
into the container, so `src/api/pdf_to_jpeg.py` kept falling through to
`autoscale.ocr_slots_default()`, which derives PDF concurrency from the container's MEMORY LIMIT.

That pin existed specifically to stop PDF concurrency from silently tracking memory. Because it was
never plumbed, cutting `APITOOLS_MEM` moved PDF slots 5 -> 3 with nothing in any diff saying so —
exactly the failure the pin was written to prevent.

The compounding harm is what makes this gate worth having: **verification lied.** A reviewer reading
`APITOOLS_MAX_CONCURRENT_PDF=5` in `.env` reasonably concluded the configuration was safe. `.env` is
INTENT; the container's environment is TRUTH. A declared-but-unplumbed knob is strictly worse than
an absent one, because an absent knob is visibly absent.

This is the ninth instance of a defect class documented in
ai/context/platform-os-consolidation.md: *an operation reports success while doing nothing.*

WHAT IT CHECKS
--------------
Every key in every profile's `env:` block must be referenced as `${KEY}` / `${KEY:-default}` in at
least one compose file under apps/ or platform-base/. That is the only mechanism by which a value in
`.env` can reach a container, so an unreferenced key provably cannot take effect.

WHAT IT DELIBERATELY DOES NOT CHECK
-----------------------------------
Whether the container's RUNNING environment matches. That needs a live stack, and a gate that only
works when the stack is up is a gate that gets skipped. Static reachability is what is provable from
the repo alone, and it catches this whole class. To verify the live half:

    docker inspect <container> --format '{{range .Config.Env}}{{println .}}{{end}}' | grep KNOB

Exit 0 = every profile knob is plumbed. Exit 1 = at least one cannot reach any container.

NUMBERING (2026-08-06): moved off G31, which `layer0-lint.py` also declared. `layer0-lint`
stays: it is referenced in GATES.md, scripts/ci/gates.sh and .github/workflows/ci-verify.yml
(5 references), while this gate is referenced in NONE of them — so this was the one that
could move for the cost of a single line. That it is unwired is its own finding: it runs in
no lane and has no GATES.md row, so nothing it asserts is currently enforced.
"""
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
PROFILES = REPO / "platform" / "profiles" / "perf-profiles.yml"
ROOTS = ("apps", "platform-base")

# Knobs that are consumed OUTSIDE a container and so are legitimately not in any compose env.
# Each entry needs a reason; an unexplained exemption here would recreate the hole this gate closes.
EXEMPT = {
    # Consumed by scripts/perf-profile-apply itself when it rewrites n8n workflow knobs in the
    # staged blueprints (`--stage`), not by any running container's environment.
}


def profile_env_keys():
    """Read `env:` keys per profile using the same shape perf-profile-apply's parser sees."""
    keys, cur, sect = {}, None, None
    for raw in PROFILES.read_text(encoding="utf-8").splitlines():
        if raw.lstrip().startswith("#"):
            continue
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        key, _, val = line.strip().partition(":")
        if indent == 0:
            cur, sect = key, None
            keys.setdefault(cur, set())
        elif indent == 2 and not val.strip():
            sect = key
        elif sect == "env" and val.strip() and cur:
            keys[cur].add(key.strip())
    return {k: v for k, v in keys.items() if v}


def compose_referenced_vars():
    """Every ${VAR} referenced anywhere in any app/base compose file."""
    ref = set()
    pat = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")
    for root in ROOTS:
        d = REPO / root
        if not d.is_dir():
            continue
        for cf in sorted(d.glob("*/docker-compose*.yml")):
            ref.update(pat.findall(cf.read_text(encoding="utf-8", errors="replace")))
    return ref


def main():
    verbose = "--verbose" in sys.argv
    if not PROFILES.exists():
        print(f"G31 FAIL — {PROFILES} not found")
        return 1

    profiles = profile_env_keys()
    referenced = compose_referenced_vars()
    all_keys = sorted({k for ks in profiles.values() for k in ks})

    missing = [k for k in all_keys if k not in referenced and k not in EXEMPT]

    print(f"G31 — {len(profiles)} profile(s), {len(all_keys)} distinct env knob(s), "
          f"{len(referenced)} var(s) referenced by compose")
    if verbose:
        for k in all_keys:
            where = "ok" if k in referenced else ("exempt" if k in EXEMPT else "NOT PLUMBED")
            print(f"    {k:<38} {where}")

    if missing:
        print(f"G31 FAIL — {len(missing)} profile knob(s) cannot reach any container:")
        for k in missing:
            owners = sorted(p for p, ks in profiles.items() if k in ks)
            print(f"    {k}   (set by: {', '.join(owners)})")
        print()
        print("  A knob in .env that no compose file references is INERT. It will read as")
        print("  configured in every review and change nothing at runtime — the defect that put a")
        print("  documented OOM-storm configuration into a live container on 2026-08-06.")
        print("  Fix: add `- KNOB=${KNOB:-}` to the environment: of the service that consumes it,")
        print("  or add it to EXEMPT in this file WITH the reason it is consumed elsewhere.")
        return 1

    print("G31 PASS — every profile knob is referenced by at least one compose file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
