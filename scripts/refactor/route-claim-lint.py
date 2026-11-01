#!/usr/bin/env python3
"""route-claim-lint — gate G21: a compose file may only route hosts its manifest declares.

    python3 scripts/refactor/route-claim-lint.py [--self-test]

WHY THIS GATE EXISTS

Two real bugs in one session, both invisible until someone opened a browser:

  * `apps/browser42` carried `traefik.http.routers.b42view-local.rule=Host(b42.localhost)` — a host
    its manifest never declared, pointing at the browser42 service, and crucially WITHOUT the
    `middlewares=authentik` that the declared host carries. An undeclared, UNAUTHENTICATED back
    door into the QA automation browser. Nothing could have caught it: the manifest looked right,
    the gated host worked, and the alias was three lines further down the label list.

  * Merging supabase-studio into `apps/supabase` carried over labels named `supabase-local/-http/
    -https` — names from when studio WAS the supabase app — whose local rule matched
    `Host(supabase.localhost) || Host(supabase-studio.localhost)`. So the API-gateway host resolved
    to Studio instead of kong, and authentik (which only had an application for the studio host)
    answered with its own Not Found page.

Both are the same defect: the compose file claims routing the manifest does not know about. The
manifest is what the compiler, the console, the authentik blueprint generator and the SSO gate all
read — so a host that exists only in a label is a host the rest of the platform cannot see.

FOUR INVARIANTS

  1. Every `Host(...)` in a router rule resolves to a host the manifest declares (or is a
     ${VAR} the compiler substitutes).
  2. Every router name begins with the app id OR one of its declared hosts, so one app cannot
     silently take over another's router. Traefik resolves routers globally by name — two apps
     with a `supabase-local` router are one deploy away from a collision no test would catch.
     `incoming-documents-local` routing `incoming-documents.localhost` is fine and
     self-documenting; `app-local` and `tf-local` are not, because nothing ties them to an owner.
  3. No `Host(...)` carries a port — not as a literal, and not through a ${VAR} whose value on
     this machine has one. traefik v3 matches Host() against the request host WITHOUT its port,
     so `Host(`plane.console.localhost:8080`)` never matches anything: the router is dead, the
     app 404s, and nothing says why. Measured 2026-09-30 with Host headers against the running
     edge (issue traefik-v3-ignores-the-request-port-so-every-ported-base-url-router-is-dead): on
     the Mac, scripts/ci-env.sh writes `<host>.localhost:8080` into every <APP>_BASE_URL, so every
     -http/-https router rendered from it was dead and each app lived on its -local twin, until
     the first nested host had no twin. The compiler strips the port (reconcile.traefik_host);
     this invariant is what keeps a new router from bypassing it. The checked surface is the
     COMPILED set (.generated/) with this machine's .env, because that is what traefik reads —
     the source files are checked for literals only. A machine without .env or .generated/ skips
     the interpolated half; it cannot be wrong there, only unproven.
  4. A host the manifest gates with `auth: sso` has NO hand-written router without the
     forward-auth middleware. The compiler puts `authentik@file` on every router it emits for
     such a host; a compose that writes its own labels (`emit_labels: false`) has to, and two did
     not. `apitools-local` carried only the retry middleware, so the production edge served
     apitools to anyone who sent `Host: apitools.localhost` (2026-09-30). And `browser42-http`
     carried none: on a `.localhost` office its rule is the SAME as `browser42-local`'s, so whether
     the automation browser asked for a sign-in depended on which of two identical rules traefik
     picked, and on a domain office plain http had no sign-in at all (found by this invariant the
     day it was written, 2026-10-07). The one exception is a router scoped to a path the routing
     entry lists in `auth_exclude` - drive's public `/file/d/` links, browser42's token-checked
     `/mcp` - so an open path is a line in the manifest, where the rest of the platform can see
     it, and not three labels further down a compose file.
"""
import json
import pathlib
import re
import sys

try:
    import yaml
except ImportError:
    print("route-claim-lint: pyyaml required", file=sys.stderr)
    raise SystemExit(2)

REPO = pathlib.Path(__file__).resolve().parents[2]
GEN = REPO / ".generated"
ENVFILE = REPO / ".env"

# Router names that predate the namespacing rule and are load-bearing across the base stack.
# Each is an accepted debt, not an exemption to copy: adding to this list needs a reason.
LEGACY_ALLOW = {
    ("traefik", "dashboard"),
    ("traefik", "api"),
}

PORTED = re.compile(r"^[A-Za-z0-9.-]+:\d+$")     # host:port — what traefik can never match


def hosts_from_rule(rule: str):
    return re.findall(r"Host\(`([^`]+)`\)", rule)


def env_values():
    """This machine's .env as {VAR: value} — last assignment wins, quotes and CR stripped, the
    same reading reconcile._envfile_value gives the compiler. Empty when there is no .env."""
    vals = {}
    if not ENVFILE.is_file():
        return vals
    for ln in ENVFILE.read_text(encoding="utf-8", errors="replace").split("\n"):
        ln = ln[:-1] if ln.endswith("\r") else ln
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", ln)
        if m:
            vals[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return vals


def router_rules(doc):
    """(service, router, rule) for every traefik router rule label in a compose document."""
    for svc, spec in (doc.get("services") or {}).items():
        labels = (spec or {}).get("labels") or []
        if isinstance(labels, dict):
            labels = [f"{k}={v}" for k, v in labels.items()]
        for label in labels:
            if not isinstance(label, str):
                continue
            m = re.match(r"traefik\.http\.routers\.([A-Za-z0-9_-]+)\.rule=(.*)", label)
            if m:
                yield svc, m.group(1), m.group(2)


def base_url_env(app_id: str) -> str:
    return app_id.upper().replace("-", "_") + "_BASE_URL"


def routers_of(spec):
    """{router: {"rule": ..., "middlewares": ...}} from one compose service's labels."""
    labels = (spec or {}).get("labels") or []
    if isinstance(labels, dict):
        labels = [f"{k}={v}" for k, v in labels.items()]
    out = {}
    for label in labels:
        m = isinstance(label, str) and re.match(
            r"traefik\.http\.routers\.([A-Za-z0-9_-]+)\.(rule|middlewares)=(.*)", label)
        if m:
            out.setdefault(m.group(1), {})[m.group(2)] = m.group(3)
    return out


def ungated(app, doc):
    """Invariant 4 over one app's own compose: [(router, service, why)] for every router that
    routes a host the manifest gates with `auth: sso` and carries no forward-auth middleware,
    unless it is scoped to a path the entry lists in `auth_exclude`.

    Which entry a router serves is read off its Host(): a literal by its first label, a ${VAR} by
    the variable the entry is published under (`url_env`, its `sso.base_url_env`, `<HOST>_BASE_URL`,
    and `<APP>_BASE_URL` when the app has one entry). A rule that names no declared host is
    invariant 1's business, not this one's."""
    entries = app.get("routing") or []
    by_host, by_var = {}, {}
    for r in entries:
        by_host[r["host"]] = r
        for var in (r.get("url_env"), (r.get("sso") or {}).get("base_url_env"), base_url_env(r["host"])):
            if var:
                by_var.setdefault(var, r)
    if len(entries) == 1:
        by_var.setdefault(base_url_env(app["id"]), entries[0])
    found = []
    for svc, spec in (doc.get("services") or {}).items():
        for router, r in sorted(routers_of(spec).items()):
            rule = r.get("rule") or ""
            served = []
            for host in hosts_from_rule(rule):
                var = re.match(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", host)
                entry = by_var.get(var.group(1)) if var else by_host.get(host.split(".")[0])
                if entry is not None and entry not in served:
                    served.append(entry)
            gated = [e for e in served if e.get("auth", "sso") == "sso"]
            if not gated:
                continue
            if any(mw.strip().split("@")[0] == "authentik" for mw in (r.get("middlewares") or "").split(",")):
                continue
            paths = re.findall(r"Path(?:Prefix)?\(`([^`]+)`\)", rule)
            open_paths = [p for e in gated for p in (e.get("auth_exclude") or [])]
            if paths and all(any(p.startswith(o) for o in open_paths) for p in paths):
                continue                                  # the declared exception
            hosts = ", ".join(sorted({e["host"] for e in gated}))
            found.append((router, svc,
                          f"routes `{hosts}`, which the manifest gates with auth: sso, and carries no "
                          f"authentik@file middleware" + (f" (its path {paths[0]} is not in `auth_exclude`)" if paths else "")))
    return found


def compiled_files():
    """The compiled compose set as traefik will see it: the include list plus the overlays that
    carry router labels. Empty when nothing was rendered on this machine."""
    top = GEN / "compose.yml"
    if not top.is_file():
        return []
    files = [top]
    try:
        doc = yaml.safe_load(top.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return files
    for inc in doc.get("include") or []:
        p = REPO / (inc if isinstance(inc, str) else inc.get("path", ""))
        if p.is_file():
            files.append(p)
    for extra in ("routing.override.yml", "connections.override.yml"):
        if (GEN / extra).is_file():
            files.append(GEN / extra)
    return files


def ported_problems():
    """Invariant 3 over the compiled set. Returns (problems, dead_weight).

    A literal host:port is always a problem. A ${VAR} that this machine's .env resolves to
    host:port renders a dead rule; that is a problem UNLESS the same service also carries a
    port-less rule for exactly that host — the `-local` twin that in fact serves it. Those twins
    are how the fifteen hand-written composes (emit_labels: false) have always worked on a Mac:
    their -http/-https routers are dead weight there, the host is still routed. Making the dead
    twins live is not a lint fix — each -http router's middleware chain would then apply on the
    Mac and needs the SSO validation the port-stripping compiler path had — so they are reported,
    not failed. What FAILS is the case that actually 404'd: a host this machine points at that no
    rule can match (plane.console.localhost, 2026-09-30)."""
    env = env_values()
    problems, dead_weight = [], []
    for path in compiled_files():
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        rel = path.relative_to(REPO).as_posix()
        rules = list(router_rules(doc))
        twins = {}                                   # service -> port-less literal hosts it routes
        for svc, _router, rule in rules:
            for host in hosts_from_rule(rule):
                if "${" not in host and not PORTED.match(host):
                    twins.setdefault(svc, set()).add(host)
        for svc, router, rule in rules:
            for host in hosts_from_rule(rule):
                if PORTED.match(host):
                    problems.append(
                        (svc, f"{rel}: router '{router}' matches Host(`{host}`) — a port inside "
                              f"Host() never matches (traefik v3 compares the host without it)"))
                for var in re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", host):
                    val = env.get(var)
                    if not (val and PORTED.match(val)):
                        continue
                    served_host = val.rsplit(":", 1)[0]
                    if served_host in twins.get(svc, ()):
                        dead_weight.append(f"{router} ({rel}: {var}={val}, served by the port-less rule for {served_host})")
                        continue
                    problems.append(
                        (svc, f"{rel}: router '{router}' interpolates {var} into Host(`{host}`), "
                              f".env gives {var}={val}, and no port-less rule on '{svc}' routes "
                              f"{served_host} — the host is unreachable; render it through "
                              f"reconcile.traefik_host()"))
    return problems, dead_weight


def main() -> int:
    problems, unkept = [], []
    for manifest in sorted(REPO.glob("apps/*/app.json")) + sorted(
        REPO.glob("platform-base/*/app.json")
    ):
        app = json.loads(manifest.read_text(encoding="utf-8"))
        aid = app["id"]
        unkept += [f"{aid}: {r['host']} {', '.join(r['auth_exclude'])}" for r in app.get("routing", [])
                   if r.get("auth_exclude") and r.get("emit_labels", True)]
        compose = manifest.parent / "docker-compose.yml"
        if not compose.exists():
            continue
        try:
            doc = yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            problems.append((aid, f"compose does not parse: {exc}"))
            continue

        declared = {r["host"] for r in app.get("routing", [])}
        rel = compose.relative_to(REPO).as_posix()
        for router, svc, why in ungated(app, doc):                       # invariant 4
            problems.append((aid, f"{rel}: router '{router}' ({svc}) {why}"))

        for svc, spec in (doc.get("services") or {}).items():
            labels = spec.get("labels") or []
            if isinstance(labels, dict):
                labels = [f"{k}={v}" for k, v in labels.items()]
            for label in labels:
                if not isinstance(label, str):
                    continue
                m = re.match(r"traefik\.http\.routers\.([A-Za-z0-9_-]+)\.rule=(.*)", label)
                if not m:
                    continue
                router, rule = m.group(1), m.group(2)

                named_ok = router.startswith(aid) or any(router.startswith(h) for h in declared)
                if not named_ok and (aid, router) not in LEGACY_ALLOW:
                    problems.append(
                        (aid, f"{rel}: router '{router}' ({svc}) is not namespaced to the app id — "
                              f"traefik resolves routers globally, so this can collide with another app"))

                for host in hosts_from_rule(rule):
                    if PORTED.match(host):                     # invariant 3, the literal half
                        problems.append(
                            (aid, f"{rel}: router '{router}' ({svc}) matches Host(`{host}`) — a port "
                                  f"inside Host() never matches; keep the port in the app's URLs"))
                    if "${" in host:          # compiler-substituted, checked in the compiled set below
                        continue
                    base = host.split(".")[0]
                    if base not in declared and base != aid:
                        problems.append(
                            (aid, f"{rel}: router '{router}' ({svc}) routes '{host}', which "
                                  f"{aid}/app.json does not declare in `routing`"))

    ported, dead_weight = ported_problems()                    # invariant 3, the interpolated half
    if problems or ported:
        print("route-claim-lint: FAIL — compose files claim routing their manifest does not declare,"
              " route a host with a port, or leave an sso host without sign-in\n")
        for aid, msg in problems + ported:
            print(f"  {aid}")
            print(f"      {msg}")
        print("\nDeclare the host in the manifest's `routing` (so SSO, the console and the")
        print("authentik blueprint generator all see it), or delete the label. A host with a port")
        print("goes through reconcile.traefik_host(), which keeps the port out of the rule. A router on")
        print("an sso host carries `middlewares=authentik@file`; a path that is open on purpose is")
        print("listed in that routing entry's `auth_exclude`.")
        return 1

    print("OK — every routed host is declared, every router is namespaced to its app, "
          "every host this machine points at has a rule that can match it, and no router of an "
          "sso host is without sign-in")
    if dead_weight:
        print(f"note: {len(dead_weight)} router(s) interpolate a value with a port and are dead on THIS "
              f"machine; each host is served by its port-less twin (hand-written composes, see "
              f"invariant 3):")
        for line in dead_weight:
            print(f"      {line}")
    if unkept:
        # Not a door — the opposite: a path the manifest says is open and the platform keeps shut.
        # The schema offers `auth_exclude` and the label emitter does not implement it, so on a
        # host the COMPILER routes it does nothing (hub sec-022: implement it, or withdraw it).
        print(f"note: {len(unkept)} routing entr{'y lists' if len(unkept) == 1 else 'ies list'} `auth_exclude` on a "
              f"host the compiler routes; the emitter does not implement it, so the path is still "
              f"behind sign-in:")
        for line in unkept:
            print(f"      {line}")
    return 0


def self_test() -> int:
    """Invariant 4 on made-up apps: what is a door, and what is the declared exception."""
    def app(*routing):
        return {"id": "demo", "routing": list(routing)}

    def doc(**routers):
        return {"services": {"demo": {"labels": [
            f"traefik.http.routers.{name}.{key}={value}"
            for name, r in routers.items() for key, value in r.items()]}}}

    sso = {"host": "demo", "port": 80, "auth": "sso"}
    rule = "Host(`demo.localhost`)"
    cases = [
        ("a router with the middleware is not a finding",
         ungated(app(sso), doc(**{"demo-local": {"rule": rule, "middlewares": "authentik@file"}})), 0),
        ("the middleware among others still counts",
         ungated(app(sso), doc(**{"demo-local": {"rule": rule, "middlewares": "demo-strip,authentik@file"}})), 0),
        ("a router of an sso host with NO middleware is a door",
         ungated(app(sso), doc(**{"demo-http": {"rule": "Host(`${DEMO_BASE_URL}`)"}})), 1),
        ("...and so is one that carries only another middleware (the apitools-local shape)",
         ungated(app(sso), doc(**{"demo-local": {"rule": rule, "middlewares": "demo-retry"}})), 1),
        ("an open PATH the manifest does not list is a door",
         ungated(app(sso), doc(**{"demo-file": {"rule": rule + " && PathPrefix(`/file/d/`)"}})), 1),
        ("an open path listed in auth_exclude is the declared exception",
         ungated(app(dict(sso, auth_exclude=["/file/d/"])),
                 doc(**{"demo-file": {"rule": rule + " && PathPrefix(`/file/d/`)"}})), 0),
        ("...but the exception is the path, not the whole host",
         ungated(app(dict(sso, auth_exclude=["/file/d/"])), doc(**{"demo-http": {"rule": rule}})), 1),
        ("a host declared auth: none needs no middleware",
         ungated(app(dict(sso, auth="none")), doc(**{"demo-local": {"rule": rule}})), 0),
        ("two hosts in one app: the open one's variable is not mistaken for the gated one's",
         ungated(app({"host": "demo", "port": 80, "auth": "none"},
                     {"host": "demo-studio", "port": 81, "auth": "sso",
                      "sso": {"base_url_env": "DEMO_STUDIO_BASE_URL"}}),
                 doc(**{"demo-api": {"rule": "Host(`${DEMO_BASE_URL}`)"},
                        "demo-studio-http": {"rule": "Host(`${DEMO_STUDIO_BASE_URL}`)"}})), 1),
    ]
    bad = 0
    for name, got, want in cases:
        ok = len(got) == want
        bad += 0 if ok else 1
        print("  [%s] %s (%d finding(s), want %d)" % ("ok " if ok else "FAIL", name, len(got), want))
    named = ungated(app({"host": "demo", "port": 80, "auth": "none"},
                        {"host": "demo-studio", "port": 81, "auth": "sso",
                         "sso": {"base_url_env": "DEMO_STUDIO_BASE_URL"}}),
                    doc(**{"demo-api": {"rule": "Host(`${DEMO_BASE_URL}`)"},
                           "demo-studio-http": {"rule": "Host(`${DEMO_STUDIO_BASE_URL}`)"}}))
    ok = [f[0] for f in named] == ["demo-studio-http"]
    bad += 0 if ok else 1
    print("  [%s] ...and the finding names the gated host's router, not the open one's" % ("ok " if ok else "FAIL"))
    print("route-claim-lint self-test: %d/%d passed" % (len(cases) + 1 - bad, len(cases) + 1))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv[1:] else main())
