#!/usr/bin/env python3
"""registry-drift-lint — gate G8: no registry may advertise an app that isn't installed.

    python3 scripts/refactor/registry-drift-lint.py
    python3 scripts/refactor/registry-drift-lint.py --self-test

The compiler owns the compose lane (include list, routing labels, the old central override).
Three registries are still HAND-MAINTAINED, and each one is a list of apps written by a human
in a second place:

    platform-base/console/modules.yaml                     the console's module tiles
    platform-base/console/app.py  APP_BASES                the /a/<alias>/ reverse-proxy table
    platform-base/authentik/blueprints/deployment-apps.yaml SSO providers + applications

Hand-maintained means they drift. They did: `feature-validation` was parked in `attic/` (not an
app, not in platform.state.yaml, no container), yet the console still shipped a tile for it and
a proxy target pointing at `http://feature-validation-api:8100`. The tile rendered, the click
502'd, and nothing failed — because no gate connected the registries to the catalog.

This gate is the connection. It does NOT yet generate the registries from the manifests (that is
the remaining plan item); it asserts the weaker but sufficient invariant that every app a
registry names is one the platform actually installs. That is what turns a silent 502 into a
build failure.

An entry is satisfied if its target matches an app id, a routing `service`, a routing `host`, or
a container name any app's compose defines — registries legitimately use all four spellings
(`/a/incoming/` -> the indox app, `/a/alerts/` -> the notifications app's `alerts-svc`).

A FOURTH REGISTRY (2026-10-07): the credential plane's own files. A provider row that carries an
`app:` block is a login — a name and an address to open, drawn under «סיסמאות אפליקציות» — and
`platform-base/connections/providers/*.yaml` is layer 1: its rows are in EVERY office's catalog.
hp-laptop runs neither GlitchTip nor chat and its screen offered both logins, each with an address.
So such a row may live there only when an app that can never be switched off (`system: true`)
consumes it. Every other app declares its own login (`contributes.connection_providers`), which the
compiler emits only while the app is installed. This check reads manifests, not the state file:
"can it be switched off" is a fact of the app, not of one office.
"""
import json, pathlib, re, sys

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "platform" / "manager"))
import reconcile  # noqa: E402 — the one reader of the state file
MODULES = REPO / "platform-base/console/modules.yaml"
CONSOLE_APP = REPO / "platform-base/console/app.py"
PROVIDERS = REPO / "platform-base/connections/providers"


def live_targets():
    """Every name the estate legitimately answers to."""
    # "Enabled" is the compiler's reading. This gate kept its own (`enabled: true` only), so an app
    # switched on the supported way (`{ state: enabled, by: … }`) did not count as running here.
    names, enabled = set(), reconcile.enabled_ids(reconcile.load_state(), reconcile.load_catalog())

    for m in sorted(list(REPO.glob("apps/*/app.json")) + list(REPO.glob("platform-base/*/app.json"))):
        a = json.loads(m.read_text(encoding="utf-8"))
        if a["id"] not in enabled:
            continue          # a disabled app has no running backend to proxy to
        names.add(a["id"])
        for r in a.get("routing") or []:
            for k in ("service", "host"):
                if r.get(k):
                    names.add(r[k])
        comp = a.get("compose")
        if comp and (m.parent / comp).exists():
            doc = yaml.safe_load((m.parent / comp).read_text(encoding="utf-8")) or {}
            names.update((doc.get("services") or {}).keys())
    return names


def app_bases():
    """The console's /a/<alias>/ -> backend-host table. Entries look like:
           "alias": os.getenv("X_URL", "http://host:port"),
    The alias is a console-local name and deliberately need NOT match a service
    (`/a/incoming/` fronts indox); what must exist is the HOST it resolves to."""
    if not CONSOLE_APP.exists():
        return {}
    src = CONSOLE_APP.read_text(encoding="utf-8")
    return dict(re.findall(r'"([a-z0-9-]+)":\s*os\.getenv\([^,]+,\s*"https?://([a-z0-9_.-]+)', src))


def stray_logins(providers, manifests):
    """[(provider id, [consumer app ids])] for every login row no system app consumes."""
    users = {}
    for a in manifests:
        for c in a.get("connections") or []:
            users.setdefault(c["id"], []).append(a)
    return [(p["id"], sorted(a["id"] for a in users.get(p["id"], [])))
            for p in providers
            if p.get("app") and not any(a.get("system") for a in users.get(p["id"], []))]


def self_test() -> int:
    """The login check on four rows: one a system app consumes, one an installable app consumes,
    one that is not a login at all, and one nobody declares."""
    apps = [{"id": "idp", "system": True, "connections": [{"id": "idp-admin"}]},
            {"id": "tracker", "connections": [{"id": "tracker-admin"}, {"id": "tracker-key"}]}]
    rows = [{"id": "idp-admin", "app": {"name": "IdP"}}, {"id": "tracker-admin", "app": {"name": "Tracker"}},
            {"id": "tracker-key"}, {"id": "orphan-login", "app": {"name": "Gone"}}]
    got, want = stray_logins(rows, apps), [("tracker-admin", ["tracker"]), ("orphan-login", [])]
    if got != want:
        print(f"G8 self-test FAIL — stray logins {got}, expected {want}")
        return 1
    print("G8 self-test PASS — a login of a switchable app is refused; a system app's, and a row that is no login, are not")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    live = live_targets()
    bases = app_bases()
    bad = []

    # 1. every proxy alias must resolve to a host the platform actually runs.
    for alias, host in sorted(bases.items()):
        if host not in live:
            bad.append(("console/app.py APP_BASES", alias, host))

    # 2. every module tile must embed either a proxy alias or a live name directly.
    if MODULES.exists():
        for e in yaml.safe_load(MODULES.read_text(encoding="utf-8")) or []:
            embed = e.get("embed")
            if not embed:
                continue      # a built-in view (dashboard/apps/install) has no backend
            tgt = embed.strip("/").split("/")[-1]
            if tgt not in bases and tgt not in live:
                bad.append(("console/modules.yaml", e.get("id"), tgt))

    # 3. every login the credential plane's own files declare is consumed by a system app.
    rows = [p for f in sorted(PROVIDERS.glob("*.yaml"))
            for p in (yaml.safe_load(f.read_text(encoding="utf-8")) or [])]
    apps = [json.loads(m.read_text(encoding="utf-8"))
            for m in sorted([*REPO.glob("apps/*/app.json"), *REPO.glob("platform-base/*/app.json")])]
    if not rows or not apps:      # a scan that read nothing has checked nothing
        print(f"G8 FAIL — {len(rows)} provider row(s) and {len(apps)} manifest(s) were read: "
              "the login check is blind, not green")
        return 1
    for pid, users in stray_logins(rows, apps):
        bad.append(("connections/providers", pid, "a login for " + (", ".join(users) or "nobody")
                    + ": declare it in that app's contributes.connection_providers"))

    if not bad:
        print(f"G8 PASS — every registry entry resolves to an installed app ({len(live)} live names), "
              f"and every login the credential plane declares is a system app's.")
        return 0

    print(f"G8 FAIL — {len(bad)} registry entr(ies) point at something the platform does not install:")
    for where, entry, tgt in bad:
        print(f"  {where}: '{entry}' -> '{tgt}'")
    print("\nEither install/enable the app, or remove the entry. A registry that advertises a")
    print("missing backend renders a tile that 502s on click.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
