#!/usr/bin/env python3
"""sso-provider-lint — gate G20: an app behind SSO must have an identity provider to be behind.

`auth: "sso"` on a routing entry makes the compiler attach the authentik forwardAuth middleware.
The authentik *application* that middleware asks about comes from a different field — `sso` — and
nothing connected the two. Declare one without the other and you get an app that is routed,
healthy, serving on its own port, and answers **404 to every request**, because traefik dutifully
asks authentik whether the caller may proceed and authentik has never heard of that host.

Found on `hello-bina`, which is the app third-party authors copy, and on `openhands`. The symptom
is maximally misleading: the container is up, the labels are right, the rule matches, traefik logs
the correct router name, and the 404 body is authentik's — so it reads like a routing bug and is
not one. It took an access-log line showing 404/3605 bytes in 47ms next to a working app's
302/703 in 1ms to see it.

The rule is one line: if a layer-3 routing entry says `auth: "sso"`, it needs an `sso` block.

…if it is ROUTED. An entry with `emit_labels: false` leaves the labels to the app's own compose,
and a service that says `traefik.enable=false` there has no router to put a middleware on: nothing
asks authentik about that host, so there is nothing to 404. `mail` declares its API service that
way on purpose (one human UI; the API is reached by name on the office network), and this gate
called it unreachable for as long as that decision has stood.

Exit 1 on any entry that would be unreachable.
"""
import glob
import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]


def unrouted(app_dir, app, entry):
    """True when the app's OWN compose keeps this entry's service off the edge."""
    if entry.get("emit_labels", True):
        return False                                # the compiler emits the router: it is routed
    try:
        import yaml
        doc = yaml.safe_load((app_dir / (app.get("compose") or "docker-compose.yml")).read_text(encoding="utf-8")) or {}
    except Exception:                               # noqa: BLE001 — unreadable: do not assume it is off
        return False
    labels = ((doc.get("services") or {}).get(entry.get("service") or app.get("id")) or {}).get("labels") or []
    if isinstance(labels, dict):
        labels = [f"{k}={v}" for k, v in labels.items()]
    return any(str(l).replace(" ", "").lower() == "traefik.enable=false" for l in labels)


def main():
    missing, checked = [], 0
    for path in sorted(glob.glob(str(REPO / "apps" / "*" / "app.json"))):
        try:
            app = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print(f"  ! {os.path.relpath(path, REPO)}: {e}")
            continue
        # Only layer 3: the base estate's providers are hand-declared in authentik's committed
        # blueprint, which is deliberate and gate G9's business, not this one's.
        if app.get("layer") != 3:
            continue
        for entry in (app.get("routing") or []):
            if entry.get("auth", "sso") != "sso":
                continue
            if unrouted(pathlib.Path(path).parent, app, entry):
                continue
            checked += 1
            if not entry.get("sso"):
                missing.append((app.get("id", "?"), entry.get("host", "?"),
                                os.path.relpath(path, REPO)))

    if missing:
        print("APPS BEHIND SSO WITH NO IDENTITY PROVIDER")
        print("-" * 76)
        for aid, host, path in missing:
            print(f"  {aid:24} host {host!r} would 404 on every request")
            print(f"  {'':24} {path}")
        print("-" * 76)
        print("  -> add an `sso` block to that routing entry:\n"
              '       "sso": { "slug": "<app>", "display_name": "<App>",\n'
              '                "default_host": "<app>.localhost",\n'
              '                "base_url_env": "<APP>_BASE_URL", "local_twin": true }\n'
              "     ...or set `auth: \"none\"` if it genuinely should not be gated.")
        print(f"\nG20 FAIL — {len(missing)} app(s) are routed behind an identity provider "
              f"that does not exist.")
        return 1

    print(f"G20 PASS — every SSO-gated app has an authentik provider ({checked} routing entr(y/ies)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
