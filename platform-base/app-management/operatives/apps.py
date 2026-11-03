#!/usr/bin/env python3
"""The control plane's app list (GET /api/apps), as the lines an agent can say: how many enabled apps
are ready, then each app that is not — a broken manifest, an app failing on its own (with the
condition that failed), or one the control plane holds because it waits on another. Given an app id,
that one app's line instead.

The apps recipe pipes into it — `./bbox app-management apps | python3
platform-base/app-management/operatives/apps.py`, `… apps.py <id>` for one app, or `/api/apps` through
`./bbox remote <office> <alias> …`, whose first line (`HTTP <status>  GET <url>`) it skips and whose
office it names. The list is every app with its conditions: read whole, the one that failed sits
where a model's context cuts it. An answer that is not an app list — or one where the control plane
could not see docker — is printed as it came and exits 1, so an office that did not answer, or was
not measured, is never reported as one where everything runs.

Not said: "running though disabled". The list's `running` counts a one-shot container that exited 0
(app.py `satisfied`), so a disabled app's count does not say anything is up.
"""
import json
import re
import sys


def flat(v):
    return re.sub(r"\s+", " ", str(v or "")).replace("|", "¦").strip()[:160]


def failed(app):
    """The first condition that is not True, as `Reason: message` — or "" when every one is."""
    for c in app.get("conditions") or []:
        if c.get("status") != "True":
            return flat(f"{c.get('reason') or c.get('type')}: {c.get('message') or ''}").rstrip(": ")
    return ""


def ready(app):
    # an app with no containers gets Ready True (NoServicesToRun) from the API itself
    return any(c.get("type") == "Ready" and c.get("status") == "True" for c in app.get("conditions") or [])


def waits_on(app):
    """`waiting on identity (forward-auth)` → "identity (forward-auth)" and "forward-auth" — only while
    all of its own containers run: one that is down is its own failure, whatever it also waits on."""
    if app.get("broken") or app.get("running") != app.get("total"):
        return None
    for c in app.get("conditions") or []:
        m = re.match(r"waiting on (.+?\(([a-z0-9-]+)\))", str(c.get("message") or ""))
        if c.get("type") == "Ready" and c.get("status") != "True" and m:
            return m.group(1), m.group(2)
    return None


def line(app, by_id):
    if app.get("broken"):
        return f"{app['id']} | BROKEN manifest — {flat(app['broken'])}"
    if not app.get("enabled"):
        return f"{app['id']} | disabled"
    run = f"{app.get('running', 0)}/{app.get('total', 0)} running"
    if ready(app):
        return f"{app['id']} | enabled | {run}, ready"
    waits = waits_on(app)
    if waits:
        # not its own failure: the control plane holds it until the app it depends on is ready
        dep = by_id.get(waits[1]) or {}
        state = ("disabled" if not dep.get("enabled") else
                 f"{flat(dep.get('state'))} ({dep.get('running', 0)}/{dep.get('total', 0)})") if dep else "unknown here"
        return f"{app['id']} | enabled | {run}, waits on {flat(waits[0])}, which is {state}"
    return f"{app['id']} | enabled | {run}, NOT ready — {failed(app) or flat(app.get('state'))}"


def main(argv):
    text = sys.stdin.read()
    office, head = "", ""
    if text.startswith("HTTP "):
        head, _, text = text.partition("\n")
        if re.match(r"HTTP [45]", head):
            print(head)
            print(text[:600])
            return 1
        m = re.search(r"//[a-z0-9-]+\.([a-z0-9-]+)[:/]", head)
        office = m.group(1) if m else ""
    try:
        listed = json.loads(text)["apps"]
        # every office has apps (traefik, the console…): an empty or malformed list is no answer
        if not isinstance(listed, list) or not listed or any(not isinstance(a, dict) or "id" not in a for a in listed):
            raise TypeError
        apps = [a for a in listed if not a.get("archived")]
    except (ValueError, KeyError, TypeError):
        print("\n".join(x for x in (head, (text or "(no answer)")[:600]) if x))
        return 1
    who = f"{office}: " if office else ""
    if any(a.get("running") is None and not a.get("broken") for a in apps):
        print(f"{who}the control plane could not see docker: no app's running state is known")
        return 1
    by_id = {a["id"]: a for a in apps}
    if argv:
        if argv[0] not in by_id:
            print(f"{who}no app named {flat(argv[0])} there")
            return 1
        print(who + line(by_id[argv[0]], by_id))
        return 0
    broken = [a for a in apps if a.get("broken")]
    enabled = [a for a in apps if a.get("enabled") and not a.get("broken")]
    off = [a for a in enabled if not ready(a) and not waits_on(a)]
    held = [a for a in enabled if not ready(a) and waits_on(a)]
    print(f"{who}{len(enabled) - len(off) - len(held)} of {len(enabled)} enabled apps ready"
          + (f", {len(off)} failing" if off else "")
          + (f", {len(held)} waiting on another app" if held else "")
          + (f", {len(broken)} with a broken manifest" if broken else ""))
    for a in broken + off + held:
        print(who + line(a, by_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
