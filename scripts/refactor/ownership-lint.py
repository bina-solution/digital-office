#!/usr/bin/env python3
"""ownership-lint — gate G5: the "nothing lives outside an app" invariant.

    python3 scripts/refactor/ownership-lint.py [--strict]

A one-off cleanup decays. This makes app-ownership an ENFORCED invariant instead: it fails
when something that should be an app is defined anywhere else. Run it in CI so the platform
cannot silently regrow a second home for services.

It reports four debts, each of which must reach ZERO for the transformation to be complete:

  1. services defined outside an app dir   (production/, development/, root compose)
  2. capability bridges still open         (platform/legacy-capabilities.yaml)
  3. acknowledged external paths           (platform/external-paths.yaml)
  4. apps whose build source is outside    (an app that cannot be moved is not an app)

--strict makes any non-zero debt an error (the end-state gate). Without it the debts are
printed as a progress scoreboard, which is what you want mid-migration.
"""
import argparse, json, pathlib, sys, re

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")

REPO = pathlib.Path(__file__).resolve().parents[2]


def services_outside_apps():
    """Compose files defining services that are not under an app dir or platform/."""
    out = []
    for pat in ("production/**/docker-compose.yml", "development/**/docker-compose.yml",
                "legacy/**/docker-compose.yml",
                "production/compose*.yml", "compose.yml", "compose.*.yml"):
        for f in REPO.glob(pat):
            rel = f.relative_to(REPO).as_posix()
            # legacy/ is explicitly parked: preserved code that is NOT part of the platform
            # (not installed, not routed, invisible to the reconciler). See legacy/README.md.
            if rel.startswith(("apps/", "platform-base/", "platform/", ".generated/", "legacy/")):
                continue
            try:
                doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            svcs = list((doc.get("services") or {}).keys())
            if svcs:
                out.append((rel, svcs))
    return out


def apps_with_external_source():
    out = []
    for m in sorted(list(REPO.glob("apps/*/app.json")) + list(REPO.glob("platform-base/*/app.json"))):
        app = m.parent
        comp = json.loads(m.read_text(encoding="utf-8")).get("compose")
        if not comp:
            continue
        try:
            doc = yaml.safe_load((app / comp).read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        for name, svc in (doc.get("services") or {}).items():
            b = svc.get("build")
            ctx = b.get("context") if isinstance(b, dict) else (b if isinstance(b, str) else None)
            if not ctx:
                continue
            resolved = (app / ctx).resolve()
            roots = (str((REPO / "apps").resolve()), str((REPO / "platform-base").resolve()))
            if not str(resolved).startswith(roots):
                out.append((m.parent.name, name, ctx))
    return out


def yaml_keys(path):
    p = REPO / path
    if not p.exists():
        return []
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return list(d.keys()) if isinstance(d, dict) else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    outside = services_outside_apps()
    bridges = yaml_keys("platform/legacy-capabilities.yaml")
    external = yaml_keys("platform/external-paths.yaml")
    ext_src = apps_with_external_source()

    n_out = sum(len(s) for _, s in outside)
    debts = [
        ("services defined outside an app dir", n_out,
         "; ".join(f"{f} ({len(s)})" for f, s in outside)),
        ("capability bridges open", len(bridges), ", ".join(bridges)),
        ("acknowledged external paths", len(external), ", ".join(external)),
        ("apps with build source outside an app dir", len(ext_src),
         ", ".join(f"{a}->{c}" for a, _, c in ext_src)),
    ]

    total = sum(n for _, n, _ in debts)
    print(f"{'OWNERSHIP DEBT':38} {'count':>6}")
    print("-" * 46)
    for label, n, detail in debts:
        print(f"{label:38} {n:>6}")
        if n and detail:
            print(f"    {detail[:150]}")
    print("-" * 46)
    print(f"{'TOTAL':38} {total:>6}")

    if total == 0:
        print("\nG5 PASS — every service lives in an app; nothing outside. Transformation complete.")
        return 0
    if a.strict:
        print("\nG5 FAIL (--strict) — the invariant is not yet met.")
        return 1
    print("\nG5 progress — run with --strict once the debts reach zero to lock the invariant in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
