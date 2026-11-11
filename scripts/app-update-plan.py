#!/usr/bin/env python3
"""app-update-plan.py — the providers `bbox update` must have up before the apps it updates (DGO-1583).

    python3 scripts/app-update-plan.py <app|service> […]

An update applies the checkout to the office that runs it. When the checkout makes an app REQUIRE a
provider this office has never run (DGO-1500 split «קבצים» into drive-local and drive-google), updating
only the app's own services left it without its providers until a whole `bbox run`. scripts/app-update.sh
asks this file for the hard closure of the apps it was named, as the compiler resolves it, and brings up
the providers that have no container at all.

stdout, one row per line, separated by spaces:
    named <argument> <app id> <root> <service>…        each argument, in the closure's dependency order (a
                                                        named provider before the app that needs it); an
                                                        argument no app declares is `named <argument> - -`, last
    provider <root> <app id> <seconds> <service>…      every OTHER app of their hard closure, in dependency
                                                        order, with the time its first start may take (its
                                                        `progress_deadline_seconds`, else 600 — as app-management
                                                        waits) and the compose services its own file declares
    later <app id> automations|sign-in                  what a provider's bring-up by an update leaves to others:
                                                        its n8n blueprints, the sign-in refresh of a host it gates
A provider that declares no compose service (a blueprint, a library) has no `provider` row. Whether an app
runs HERE is the compiled office's answer (`scripts/dc config --services`), not this file's.

Exit 0; 1 when the compiler refuses the closure (its errors on stderr); 2 on usage.
"""
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "platform" / "manager"))
import reconcile  # noqa: E402 — the compiler's own resolution, never a copy of it

FIRST_START = 600      # app-management's DEFAULT_PROGRESS_DEADLINE: an app that declares none gets this


def owner(cat, name):
    """The app id `name` is, or the app whose compose file declares a service called `name`; None."""
    if name in cat:
        return name
    return next((aid for aid in sorted(cat) if name in reconcile.compose_services(cat[aid])), None)


def main(argv):
    if not argv:
        print("usage: app-update-plan.py <app|service> […]", file=sys.stderr)
        return 2
    cat, state = reconcile.load_catalog(), reconcile.load_state()
    named = [(name, owner(cat, name)) for name in argv]
    roots = []
    for _, aid in named:
        if aid and aid not in roots:
            roots.append(aid)
    order = []
    if roots:
        order, diags = reconcile.resolve(cat, state, roots=roots)
        errors = [m for level, m in diags if level == "error"]
        for m in errors:
            print("  ERROR " + m, file=sys.stderr)
        if errors:
            return 1
    rank = {aid: i for i, aid in enumerate(order)}
    for name, aid in sorted(named, key=lambda x: rank.get(x[1], len(rank))):
        if aid:
            print("named", name, aid, pathlib.Path(cat[aid]["_dir"]).parent.name, *reconcile.compose_services(cat[aid]))
        else:
            print("named", name, "-", "-")
    for aid in order:
        if aid in roots:
            continue
        app = cat[aid]
        services = reconcile.compose_services(app)
        if not services:
            continue
        seconds = int(app.get("progress_deadline_seconds") or FIRST_START)
        print("provider", pathlib.Path(app["_dir"]).parent.name, aid, seconds, *services)
        if (app.get("blueprints") or {}).get("n8n"):
            print("later", aid, "automations")
        if any((r or {}).get("auth") == "sso" for r in app.get("routing") or []):
            print("later", aid, "sign-in")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
