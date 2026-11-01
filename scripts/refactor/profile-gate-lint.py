#!/usr/bin/env python3
"""profile-gate-lint — gate G22: no app may gate its services behind a compose profile.

    python3 scripts/refactor/profile-gate-lint.py

WHY THIS GATE EXISTS

`apps/browser42` carried `profiles: [browser42]` on all four of its services. That is a SECOND
source of truth for whether an app runs, sitting underneath the one the whole platform is built on.

The failure it produced was invisible from every angle that matters:

    platform.state.yaml   browser42: { enabled: true }     <- operator says run it
    reconcile.py plan     browser42 in the start order     <- compiler agrees
    compose (the engine)  omits all four services          <- COMPOSE_PROFILES was empty
    apps screen           Open -> browser42.localhost      <- 404, nothing behind the route

The app was enabled, the compiler had included it, and the containers simply did not exist. No
error anywhere — compose treats an unmatched profile as "not requested", not as a problem.

`platform.state.yaml` decides what runs. That is the entire premise of the disposition model
(enabled / disabled / archived), and an app that quietly adds a second switch breaks the promise
that the state file is the only file the console writes and the only thing that decides.

If a service genuinely should not always start, express it in the manifest — ship the app
disabled, or split it into its own gallery app. Both are visible in `platform.state.yaml`; a
compose profile is not.
"""
import pathlib
import sys

try:
    import yaml
except ImportError:
    print("profile-gate-lint: pyyaml required", file=sys.stderr)
    raise SystemExit(2)

REPO = pathlib.Path(__file__).resolve().parents[2]


def main() -> int:
    problems = []
    for compose in sorted(REPO.glob("apps/*/docker-compose.yml")) + sorted(
        REPO.glob("platform-base/*/docker-compose.yml")
    ):
        try:
            doc = yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            problems.append((compose, "<file>", f"does not parse: {exc}"))
            continue
        for svc, spec in (doc.get("services") or {}).items():
            if not isinstance(spec, dict):
                continue
            profiles = spec.get("profiles")
            if profiles:
                problems.append((compose, svc, f"profiles: {profiles}"))

    if problems:
        print("profile-gate-lint: FAIL — a compose profile is a second switch for whether an app runs\n")
        for compose, svc, detail in problems:
            print(f"  {compose.relative_to(REPO).as_posix()}")
            print(f"      service '{svc}' declares {detail}")
        print("\nplatform.state.yaml decides what runs. An app enabled there whose services sit")
        print("behind an unmatched profile is compiled in, routed, and then simply absent — a 404")
        print("with nothing behind it and no error anywhere. Ship the app disabled instead, or")
        print("split it into its own gallery app; both are visible in the state file.")
        return 1

    print("OK — no app gates its services behind a compose profile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
