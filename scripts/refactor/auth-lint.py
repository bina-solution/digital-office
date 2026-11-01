#!/usr/bin/env python3
"""auth-lint — gate G6: no SSO bypass via colliding traefik router rules.

    python3 scripts/refactor/auth-lint.py [.refactor/candidate.yml]

The bug this exists for: services declare three routers — <name>-local on <host>.localhost,
plus -http and -https on ${APP_BASE_URL}. Only -local and -https carried the authentik
middleware, because ${APP_BASE_URL} was assumed to be a distinct public domain. Set
DEPLOYMENT_DOMAIN=localhost (which a local/dev deployment does) and ${APP_BASE_URL} becomes
<host>.localhost — the SAME rule as -local — but the -http twin has NO auth. Traefik may serve
the unprotected one and SSO is silently bypassed.

Found live on 5 services including the Traefik dashboard and Supabase Studio.

Rule enforced: if two routers share an identical rule and ANY of them is authenticated, then
ALL of them must be. Authentication must never depend on which of two identical rules traefik
happens to pick.

Exit 0 = no bypass. Exit 1 = at least one unprotected twin of a protected route.
"""
import subprocess
import sys, re, collections, pathlib

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")


def labels_of(svc):
    l = svc.get("labels") or []
    return [f"{k}={v}" for k, v in l.items()] if isinstance(l, dict) else list(l)


REPO = pathlib.Path(__file__).resolve().parents[2]


def _default_input():
    """The routing overlay the platform actually deploys.

    This used to default to `.refactor/candidate.yml`, an artifact of the three-layer refactor.
    Nothing under .refactor/ is tracked, so on any fresh clone the gate did not report a
    finding — it raised FileNotFoundError and died, which reads as a broken runner rather than
    an ungated route. A gate whose input no longer exists is not a gate.

    `.generated/routing.override.yml` is where router labels come from now: reconcile.py writes
    every app's `routing` block into it, so this checks what will actually be served rather than
    a snapshot of what was once proposed. It is generated (gitignored), so render it if absent.
    """
    gen = REPO / ".generated" / "routing.override.yml"
    if not gen.exists():
        subprocess.run([sys.executable, str(REPO / "platform" / "manager" / "reconcile.py"), "render"],
                       cwd=str(REPO), capture_output=True)
    if not gen.exists():
        sys.exit("G6 could not produce .generated/routing.override.yml — run "
                 "`python3 platform/manager/reconcile.py render` and re-run this gate.")
    return gen


def main():
    cand = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else _default_input()
    cfg = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}

    bad, checked = [], 0
    for name, svc in (cfg.get("services") or {}).items():
        rules, authed = {}, set()
        for l in labels_of(svc):
            m = re.match(r"traefik\.http\.routers\.([\w-]+)\.rule=(.+)", l)
            if m:
                rules[m.group(1)] = m.group(2)
            m = re.match(r"traefik\.http\.routers\.([\w-]+)\.middlewares=", l)
            if m:
                authed.add(m.group(1))
        by = collections.defaultdict(list)
        for r, v in rules.items():
            by[v].append(r)
        for rule, rs in by.items():
            if len(rs) < 2:
                continue
            checked += 1
            prot = [r for r in rs if r in authed]
            unprot = [r for r in rs if r not in authed]
            if prot and unprot:
                bad.append((name, rule, unprot))

    if bad:
        print(f"G6 FAIL — {len(bad)} SSO bypass(es): an unprotected router shares a rule with a protected one")
        for svc, rule, unprot in bad:
            print(f"  {svc:22} {rule[:46]:48} unprotected: {', '.join(unprot)}")
        return 1
    print(f"G6 PASS — no colliding rule has a mix of protected/unprotected routers ({checked} collision group(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
