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

INVARIANTS (1–5 below; 6–8 and 9 are told at their functions and in GATES.md G21: 6 a declared middleware
exists, 7 every `websecure` router carries hsts@file, 8 an https-only host has no router of its own on `web`, 9 root
on the host is the admins' and never behind an open door)

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
  5. Two routing entries of one app whose labels the COMPILER emits never share a router name. It
     names a router `routing[].name or app_id` (reconcile.routing_labels, and the Go twin), so two
     entries without a name on two services both declared `<app>-local/-http/-https` with different
     rules — and traefik drops a router two containers define differently. bina-claude shipped that
     way (its desktop and its terminal); neither tile was routed on the HP's own edge (DGO-1269,
     fixed in c34d99b6). Read from the manifest alone, as the compiler reads it.
"""
import json
import pathlib
import posixpath
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
# The office's sign-in middlewares (platform-base/traefik/config/authentik-forwardauth.yaml): any app's sso router
# carries one; an app whose app.json says `people: admins` carries the second, which refuses everyone but the
# office's admins (DGO-1755).
SIGN_INS = {"authentik", "authentik-admins"}
ADMINS_ONLY = {"authentik-admins"}


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


def router_entries(app):
    """The manifest's `routing` rows that are ROUTERS — the ones that publish a host.

    A row of `routing` is not necessarily a router: it may instead EMBED a console module on a
    service the app already routes (`{"port": …, "service": …, "auth": "none", "module": {…}}`,
    with no `host` — drive's `recorder` tile). Such a row publishes no route of its own, so it
    claims no host; reading `r["host"]` off it is what crashed this gate. The compiler draws the
    same line (`reconcile.py`, CONFLICTS: `if r.get("host")`), so this is the manifest's own
    meaning of the word, not a workaround."""
    return [r for r in (app.get("routing") or []) if r.get("host")]


def ungated(app, doc):
    """Invariant 4 over one app's own compose: [(router, service, why)] for every router that
    routes a host the manifest gates with `auth: sso` and carries no forward-auth middleware,
    unless it is scoped to a path the entry lists in `auth_exclude`.

    Which entry a router serves is read off its Host(): a literal by its first label, a ${VAR} by
    the variable the entry is published under (`url_env`, its `sso.base_url_env`, `<HOST>_BASE_URL`,
    and `<APP>_BASE_URL` when the app has one entry). A rule that names no declared host is
    invariant 1's business, not this one's."""
    entries = router_entries(app)
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
            # an app of the office's admins (`people: admins`, DGO-1755) is signed in by the middleware that also
            # refuses everyone else; any other app by either
            names = {mw.strip().split("@")[0] for mw in (r.get("middlewares") or "").split(",")}
            if names & (ADMINS_ONLY if app.get("people") == "admins" else SIGN_INS):
                continue
            if app.get("people") == "admins" and names & SIGN_INS:
                found.append((router, svc, "carries authentik@file, but the app says `people: admins`: its sign-in "
                                           "is authentik-admins@file, which refuses everyone but the office's admins"))
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


def missing_middlewares(app, doc):
    """Invariant 6: every middleware a manifest DECLARES exists in that app's own compose.

    `routing[].middlewares` and `routing[].sub_routes[].middlewares` are names the compiler renders
    as `<name>@docker` onto routers it emits. traefik DISCARDS a whole router whose middleware it
    cannot resolve (measured 2026-07-30: 3,718 router rejections and every gated surface dark while
    the stack reported healthy), and a label-defined middleware exists only on the service that
    declares it — so a typo, or a name that belongs to another app, silently removes a route instead
    of failing. n8n is the first app to declare any (DGO-1594: `n8n-embed`, and the two Origin
    middlewares its `/rest/push` sub-routes carry); nothing read those names until this did.

    A name carrying its own provider (`x@file`) is refused as well: the provider is the emitter's to
    append, and a file-provider middleware is the platform's, not an app's to borrow."""
    declared = list(app.get("middlewares") or [])
    for r in (app.get("routing") or []):
        declared += list(r.get("middlewares") or [])
        for sub in (r.get("sub_routes") or []):
            declared += list(sub.get("middlewares") or [])
    if not declared:
        return []
    defined = set()
    for spec in (doc.get("services") or {}).values():
        labels = (spec or {}).get("labels") or []
        if isinstance(labels, dict):
            labels = [f"{k}={v}" for k, v in labels.items()]
        for label in labels:
            m = isinstance(label, str) and re.match(
                r"traefik\.http\.middlewares\.([A-Za-z0-9_-]+)\.", label)
            if m:
                defined.add(m.group(1))
    out = []
    for name in declared:
        if not isinstance(name, str) or "@" in name:
            out.append((name, "carries its own provider — a declared middleware is one the app's own "
                               "compose defines; the emitter appends `@docker` itself"))
        elif name not in defined:
            out.append((name, "is not defined by a `traefik.http.middlewares.%s.…` label in this "
                               "app's own docker-compose.yml" % name))
    return out


def missing_hsts(app, doc, rel):
    """Invariant 7: every router on the `websecure` entrypoint carries `hsts@file` (DGO-1595).

    A certificate that does not pin https leaves the downgrade open on the NEXT request: the edge
    redirects port 80 (the `dgo-port80` router), and the browser only remembers to go to https
    because an https answer told it to. Measured 2026-11-09: `http://n8n.exampleu…/` served the editor
    in cleartext and no office sent `Strict-Transport-Security` anywhere.

    The middleware is defined in the compiler's generated `zz-https.yaml` on EVERY office (a router
    whose middleware does not resolve is DROPPED whole by traefik), and it is referenced on a
    SERVER office only — so this invariant is about the tree, not about one deployment: a router
    that names `websecure` must name the pin.

    And name it FIRST (2026-11-17): a middleware that answers by itself — the sign-in's 302, a
    redirect — ends the chain, so a pin after it is never written. Measured on vps1: the console and
    n8n answered a signed-out visitor's 302 with no Strict-Transport-Security under
    `authentik@file,hsts@file`; present-anywhere was the check this invariant made, and it passed."""
    out = []
    labels = []
    for spec in (doc.get("services") or {}).values():
        ls = (spec or {}).get("labels") or []
        if isinstance(ls, dict):
            ls = [f"{k}={v}" for k, v in ls.items()]
        labels += [l for l in ls if isinstance(l, str)]
    routers = {}
    for label in labels:
        m = re.match(r"traefik\.http\.routers\.([A-Za-z0-9_-]+)\.(entrypoints|middlewares)=(.*)", label)
        if m:
            routers.setdefault(m.group(1), {})[m.group(2)] = m.group(3)
    for name, spec in sorted(routers.items()):
        if "websecure" not in (spec.get("entrypoints") or ""):
            continue
        chain = [m.strip() for m in (spec.get("middlewares") or "").split(",") if m.strip()]
        if "hsts@file" not in chain:
            out.append(f"{rel}: router '{name}' is on websecure and carries no hsts@file")
        elif chain[0] != "hsts@file":
            out.append(f"{rel}: router '{name}' carries hsts@file after {chain[0]} — it must come first, or "
                       "a middleware that answers by itself (the sign-in's 302) ends the chain before it")
    return out


def https_only_violations(app, doc, rel, env):
    """Invariant 8: a host declared `https_only` (or declared `publish: "domain"` in an office that
    publishes nothing) has no hand-written router of its own on `web` (DGO-1557).

    The shape this refuses is the one that shipped: `apps/supabase` wrote its own `supabase-api`
    router on the `web` entrypoint with no middleware and no https twin, so the API (rest, storage,
    `/pg/` SQL) answered the internet in plain HTTP on a server office while the https addresses it
    hands to browsers had no router at all. A host that carries an API is declared, and the compiler
    emits it — https only, and only where the office names a real host."""
    out = []
    for r in (app.get("routing") or []):
        if not r.get("host"):
            continue
        host = str(r.get("host"))
        var = str(r.get("url_env") or base_url_env(str(app.get("id") or host)))
        http_only = []
        for name, spec in routers_of_any(doc).items():
            rule = spec.get("rule") or ""
            if host not in [h.split(".")[0] for h in re.findall(r"Host\(`([^`]+)`\)", rule)] \
                    and not any(h.startswith("${") and var in h for h in re.findall(r"Host\(`([^`]+)`\)", rule)):
                continue
            eps = spec.get("entrypoints") or ""
            if re.search(r"\bweb\b", eps) and "websecure" not in eps:
                http_only.append(name)
        if not http_only:
            continue
        if r.get("https_only"):
            out.append(f"{rel}: router {', '.join(http_only)} serves '{host}' on web, and its entry "
                       f"declares https_only — an API host is https and nothing else")
        elif (r.get("publish") or "always") == "domain":
            value = (env.get(var) or "").split("//")[-1].split("/")[0].split(":")[0].lower()
            if value and ("." not in value or value.endswith(".localhost")):
                out.append(f"{rel}: router {', '.join(http_only)} publishes '{host}' on web, while "
                           f"{var} names an office that publishes nothing ({value})")
    return out


def routers_of_any(doc):
    """{router: {"rule": …, "entrypoints": …, "middlewares": …}} from every service of a compose.

    `routers_of` reads rule and middlewares only (that is all the older invariants ask); the entry
    list is read here, because "on `web` alone" is exactly what DGO-1557's invariant 8 judges."""
    out = {}
    for spec in (doc.get("services") or {}).values():
        for name, kv in routers_of(spec).items():
            out.setdefault(name, {}).update(kv)
        labels = (spec or {}).get("labels") or []
        if isinstance(labels, dict):
            labels = [f"{k}={v}" for k, v in labels.items()]
        for label in labels:
            m = isinstance(label, str) and re.match(
                r"traefik\.http\.routers\.([A-Za-z0-9_-]+)\.entrypoints=(.*)", label)
            if m:
                out.setdefault(m.group(1), {})["entrypoints"] = m.group(2)
    return out


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


SOCKETS = ("docker.sock", "containerd.sock", "docker.sock.raw")       # .raw: Docker Desktop's own
SOCKET_DIRS = {"/run", "/var/run", "/run/containerd", "/var/run/containerd"}   # a bind of these carries the socket


def compose_value(text) -> str:
    """A compose value read the way the check needs it. `${V:-d}`/`${V-d}` is its default and `${V:+w}`/`${V+w}`
    the word it takes when the variable IS set — the reading that can put a socket there (nested ones resolved
    inside out); a variable with no default (`$V`, `${V}`, `${V:?err}`) becomes `@V@`, so a `…DOCKER_SOCK` variable
    is still recognised by its name. `$$` is compose's escaped `$`, and stays text."""
    text = str(text).replace("$$", "\0")
    text = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r"@\1@", text)
    inner = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?+])([^${}]*))?\}")
    prev = None
    while text != prev:
        prev = text
        text = inner.sub(lambda m: m.group(3) if m.group(2) in ("-", ":-", "+", ":+") else f"@{m.group(1)}@", text)
    return text.replace("\0", "$")


def compose_vars(text) -> set:
    """Every variable a compose value names, defaults included (`${A:-${B}}` → {A, B}); `$$X` is text, not one."""
    return set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", str(text).replace("$$", "")))


def root_mounts(doc) -> list:
    """[(service, source)] of the BIND mounts that make a container root on the HOST: the docker or containerd socket
    (`…docker.sock`, the office's own `bbox-docker.sock` included, or a variable named `…DOCKER_SOCK`,
    `…DOCKER_SOCK_…` or `…DOCKER_SOCKET` whatever its default), anything mounted ONTO a socket path whatever its
    source, a directory that holds one (`/run`, `/var/run`, containerd's), and the host's own root (`/`, `//`, `/.`). Read from the
    compose's volumes, short (`src:dst[:mode]`) and long (`source:`) forms — never from a comment — and a named volume
    is read through its top-level declaration: the local driver's `o: bind` + `device:` is a bind of that device. Any
    other named or anonymous volume and a tmpfs live in docker's own storage and are not asked. What the invariant
    does not ask at all is said in GATES.md."""
    top = (doc or {}).get("volumes") or {}

    def device(name):                              # `volumes: {x: {driver_opts: {o: bind, device: /}}}` → "/"
        opts = ((top.get(name) or {}).get("driver_opts") or {}) if isinstance(top, dict) else {}
        return compose_value(opts.get("device", "")).strip() if "bind" in str(opts.get("o", "")) else ""

    out = []
    for svc, spec in ((doc or {}).get("services") or {}).items():
        for vol in (spec or {}).get("volumes") or []:
            if isinstance(vol, dict):
                if vol.get("type") in ("tmpfs", "npipe", "cluster", "image"):
                    continue
                src_raw, dst_raw, kind = str(vol.get("source", "")), str(vol.get("target", "")), vol.get("type")
            else:
                parts = split_short(vol)
                if len(parts) < 2:                                   # `- /var/run/docker.sock`: an anonymous volume
                    continue
                src_raw, dst_raw, kind = parts[0], parts[1], None
            src, dst = compose_value(src_raw).strip(), compose_value(dst_raw).strip()
            names = compose_vars(src_raw)
            by_name = any(SOCK_VAR.search(n) for n in names)            # BBOX_DOCKER_SOCK, not DOCKER_SOCKET_…
            to_socket = posixpath.basename(dst) in SOCKETS
            if kind == "volume" or not src.startswith(("/", ".", "~", "@")):
                if device(src):                                      # a named volume the local driver binds
                    src = device(src)
                elif kind == "volume" or not (names and (by_name or to_socket)):
                    continue                                         # `docker.sock:/x`: a volume of that NAME
                else:                                                # `${BBOX_DOCKER_SOCK:-}:…`: the office's
                    src = src or src_raw                             # variable, whatever its default
            path = posixpath.normpath(src) if src.startswith("/") else src
            if (path.strip("/") == "" and src.startswith("/")) or path in SOCKET_DIRS \
                    or posixpath.basename(path).endswith(SOCKETS) or by_name or to_socket:
                out.append((svc, src))
    return out


SOCK_VAR = re.compile(r"DOCKER_SOCK(?![A-Za-z])|DOCKER_SOCKET$")   # BBOX_DOCKER_SOCK, DOCKER_SOCK_PATH, DOCKER_SOCKET


def split_short(text) -> list:
    """A short-form volume `src:dst[:mode]` split on the colons OUTSIDE `${…}` (`${S:-/a}:/b` is two parts)."""
    parts, cur, depth, s, i = [], "", 0, str(text), 0
    while i < len(s):
        if s.startswith("${", i):
            depth, cur, i = depth + 1, cur + "${", i + 2
            continue
        if s[i] == "}" and depth:
            depth -= 1
        if s[i] == ":" and not depth:
            parts.append(cur)
            cur = ""
        else:
            cur += s[i]
        i += 1
    return parts + [cur]


def signed_in_doors(app) -> list:
    """The app's routes a person signs into: an `sso` host, and any console tile (`module.alias`) — the console serves
    `/a/<alias>/` behind its own sign-in whatever the route's `auth` says (reconcile's module doors)."""
    return [r for r in (app.get("routing") or [])
            if (r.get("host") and r.get("auth", "sso") == "sso") or (r.get("module") or {}).get("alias")]


def root_without_admins(app, doc) -> list:
    """Invariant 9 (DGO-1755): an app whose containers are root on the host — the docker socket, the host's `/` —
    and that a person signs into is the office's admins' alone: `people: admins`. Otherwise every person the owner
    invites opens a door to the host."""
    if app.get("people") == "admins" or not signed_in_doors(app):
        return []
    return root_mounts(doc)


# Invariant 9's declared exceptions: (app, router) → why that open router may reach a container that is root on the
# host. Each is a debt with its item, not a permission; a declaration that stops matching a router FAILS (stale).
OPEN_ROOT_KNOWN = {
    # empty since DGO-1794: connections' /oauth/relay was the one, served by the container that held the docker
    # socket; connections now reads the engine through its own read-only door and holds no socket.
}


def root_in_public(app, doc) -> list:
    """Invariant 9, its other half: a door nobody signs into is open to whoever reaches the edge, and `people: admins`
    does not close it (the admins' middleware rides the sso routers only). [(door, service, source)] for each open
    door to a service that mounts root: a host the manifest serves with `auth: none` (the route's `service`, else the
    app's id), and a router the compose writes on that service without a sign-in middleware — an `auth_exclude`
    path's router among them. Routers in OPEN_ROOT_KNOWN are the declared exceptions."""
    mounts = root_mounts(doc)
    rooted = {s for s, _ in mounts}
    out = []
    for r in app.get("routing") or []:
        if r.get("host") and r.get("auth", "sso") == "none":
            svc = r.get("service") or app.get("id")
            out += [(f"host '{r['host']}' (auth: none)", s, src) for s, src in mounts if s == svc]
    for svc, spec in ((doc or {}).get("services") or {}).items():
        if svc not in rooted:
            continue
        for router, r in sorted(routers_of(spec).items()):
            names = {mw.strip().split("@")[0] for mw in (r.get("middlewares") or "").split(",")}
            if not r.get("rule") or names & SIGN_INS or (app.get("id"), router) in OPEN_ROOT_KNOWN:
                continue
            out += [(f"router '{router}' (no sign-in middleware)", s, src) for s, src in mounts if s == svc]
    return out


def stale_open_root(app, doc) -> list:
    """The OPEN_ROOT_KNOWN routers of this app that no longer exist, or no longer reach a root mount, or carry a
    sign-in now: a declaration about nothing is a finding, so the list can only shrink by being edited."""
    rooted = {s for s, _ in root_mounts(doc)}
    live = set()
    for svc, spec in ((doc or {}).get("services") or {}).items():
        for router, r in routers_of(spec).items():
            names = {mw.strip().split("@")[0] for mw in (r.get("middlewares") or "").split(",")}
            if svc in rooted and r.get("rule") and not names & SIGN_INS:
                live.add(router)
    return [router for (aid, router) in OPEN_ROOT_KNOWN if aid == app.get("id") and router not in live]


def main() -> int:
    problems, unkept = [], []
    read = {"manifests": 0, "composes": 0}
    seen_apps = set()
    for manifest in sorted(REPO.glob("apps/*/app.json")) + sorted(
        REPO.glob("platform-base/*/app.json")
    ):
        read["manifests"] += 1
        app = json.loads(manifest.read_text(encoding="utf-8"))
        aid = app["id"]
        unkept += [f"{aid}: {r['host']} {', '.join(r['auth_exclude'])}" for r in router_entries(app)
                   if r.get("auth_exclude") and r.get("emit_labels", True)]
        for name, hosts in router_name_clashes(app):                      # invariant 5
            problems.append((aid, f"{manifest.relative_to(REPO).as_posix()}: routing entries for "
                                  f"{', '.join(hosts)} all compile to routers named '{name}-*' — "
                                  f"traefik drops a router two containers define differently; give "
                                  f"each entry after the first its own `name`"))
        compose = manifest.parent / "docker-compose.yml"
        if not compose.exists():
            continue
        try:
            doc = yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            problems.append((aid, f"compose does not parse: {exc}"))
            continue
        read["composes"] += 1

        declared = {r["host"] for r in router_entries(app)}
        rel = compose.relative_to(REPO).as_posix()
        for router, svc, why in ungated(app, doc):                       # invariant 4
            problems.append((aid, f"{rel}: router '{router}' ({svc}) {why}"))
        for mw, why in missing_middlewares(app, doc):                    # invariant 6
            problems.append((aid, f"{rel}: the manifest declares the middleware '{mw}', which {why} "
                                  f"— traefik drops the whole router and the app answers nothing"))
        for msg in missing_hsts(app, doc, rel):                          # invariant 7
            problems.append((aid, msg))
        for msg in https_only_violations(app, doc, rel, env_values()):    # invariant 8 (DGO-1557)
            problems.append((aid, msg))
        for svc, src in root_without_admins(app, doc):                   # invariant 9 (DGO-1755)
            problems.append((aid, f"{rel}: service '{svc}' mounts {src} (root on the host) and a person signs in "
                                  f"to the app — its app.json must say `\"people\": \"admins\"`, or every person "
                                  f"the owner invites opens a door to the host"))
        for door, svc, src in root_in_public(app, doc):                  # invariant 9, the open half
            problems.append((aid, f"{rel}: {door} is open to whoever reaches the edge and reaches service '{svc}', "
                                  f"which mounts {src} (root on the host) — `people: admins` does not close an open "
                                  f"door; serve it from a service without the mount, or sign it in"))
        for router in stale_open_root(app, doc):
            problems.append((aid, f"{rel}: OPEN_ROOT_KNOWN declares the open router '{router}', which no longer "
                                  f"reaches a root mount without a sign-in — delete the declaration"))
        seen_apps.add(aid)

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

    for aid, router in OPEN_ROOT_KNOWN:                       # invariant 9: a declaration about an app not read
        if aid not in seen_apps:
            problems.append((aid, f"OPEN_ROOT_KNOWN declares '{router}' of an app with no compose read — delete the "
                                  f"declaration"))
    ported, dead_weight = ported_problems()                    # invariant 3, the interpolated half
    if problems or ported:
        print("route-claim-lint: FAIL — compose files claim routing their manifest does not declare,"
              " route a host with a port, leave an sso host without sign-in, declare a middleware\n"
              " that does not exist, serve https without pinning it, or open a door to root on the host\n")
        for aid, msg in problems + ported:
            print(f"  {aid}")
            print(f"      {msg}")
        print("\nDeclare the host in the manifest's `routing` (so SSO, the console and the")
        print("authentik blueprint generator all see it), or delete the label. A host with a port")
        print("goes through reconcile.traefik_host(), which keeps the port out of the rule. A router on")
        print("an sso host carries `middlewares=authentik@file`; a path that is open on purpose is")
        print("listed in that routing entry's `auth_exclude`. A middleware a manifest declares is")
        print("one the app's own compose defines on its own service's labels (the provider is the")
        print("emitter's to append) — a name traefik cannot resolve drops the whole router.")
        return 1

    if not read["manifests"] or not read["composes"]:
        print("route-claim-lint: FAIL — it read no manifest or no compose: a gate that reads nothing passes nothing")
        return 1
    print("OK — every routed host is declared, every router is namespaced to its app, "
          "every host this machine points at has a rule that can match it, and no router of an "
          "sso host is without sign-in "
          f"({read['manifests']} manifests and {read['composes']} composes read)")
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
              f"host the compiler routes; the emitter does not implement it, so the routers IT emits "
              f"still gate that path. An app that serves the open half from a router of its own — "
              f"n8n's `/webhook/`, `/webhook-waiting/` and `/form/` on `n8n-webhook` — is public "
              f"there, and this note is about the compiled half only:")
        for line in unkept:
            print(f"      {line}")
    return 0


def router_name_clashes(app) -> list:
    """Invariant 5: the router names two or more compiler-emitted routing entries of `app` share."""
    seen: dict = {}
    for r in app.get("routing") or []:
        if not isinstance(r, dict) or not r.get("host") or not r.get("emit_labels", True):
            continue                     # no host: no router; emit_labels false: the app's own labels
        name = r.get("name") or app.get("id")
        seen.setdefault(name, []).append(r["host"])
    return [(name, hosts) for name, hosts in seen.items() if len(hosts) > 1]


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
        ("a MODULE-only row (no host) is not a router: the sso host it rides is still a door",
         ungated(app(sso, {"port": 80, "service": "demo", "auth": "none",
                           "emit_labels": False, "module": {"id": "demo-rec", "alias": "rec"}}),
                 doc(**{"demo-http": {"rule": rule}})), 1),
        ("...and a module-only row alone neither crashes nor invents a host to gate",
         ungated(app({"port": 80, "service": "demo", "auth": "none",
                      "module": {"id": "demo-rec", "alias": "rec"}}),
                 doc(**{"demo-local": {"rule": rule, "middlewares": "authentik@file"}})), 0),
        # DGO-1755: an app of the office's admins carries the sign-in that refuses everyone else
        ("an admins' app with authentik-admins@file is not a finding",
         ungated(dict(app(sso), people="admins"),
                 doc(**{"demo-local": {"rule": rule, "middlewares": "authentik-admins@file"}})), 0),
        ("an admins' app's own router with authentik@file is a door for every signed-in person",
         ungated(dict(app(sso), people="admins"),
                 doc(**{"demo-local": {"rule": rule, "middlewares": "authentik@file,hsts@file"}})), 1),
        ("an everyone app may carry either",
         ungated(app(sso), doc(**{"demo-local": {"rule": rule, "middlewares": "authentik-admins@file"}})), 0),
        # invariant 9: root on the host and signed into is the admins'
        ("an everyone app that mounts the docker socket is a door to the host",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["/var/run/docker.sock:/var/run/docker.sock"]}}}),
         1),
        ("…so is one that mounts the host's root, in the long form",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": [{"type": "bind", "source": "/",
                                                                              "target": "/host", "read_only": True}]}}}),
         1),
        ("…and the office's socket through a variable's default",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": [
             "${BBOX_DOCKER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock:ro"]}}}), 1),
        ("…the admins' app may", root_without_admins(dict(app(sso), people="admins"),
                                                    {"services": {"demo": {"volumes": ["/run/bbox-docker.sock:/s"]}}}), 0),
        ("…an app with no route at all (a socket proxy, autoheal) is not this invariant's",
         root_without_admins(app(), {"services": {"demo": {"volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"]}}}),
         0),
        ("…and a file that only has the socket in its name is not one",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["./docs/docker.sock.md:/d"]}}}), 0),
        # the reader's shapes (2026-11-10): what must not slip by…
        ("a variable that must be set (`${S:?…}`) and names the socket",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": [
             "${BBOX_DOCKER_SOCK:?set it}:/var/run/docker.sock"]}}}), 1),
        ("…the same in the long form",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": [
             {"type": "bind", "source": "${S:?e}", "target": "/var/run/docker.sock"}]}}}), 1),
        ("…a nested default",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": [
             "${A:-${B:-/var/run/docker.sock}}:/s"]}}}), 1),
        ("…the office's variable with no default, bound anywhere",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["${BBOX_DOCKER_SOCK}:/x"]}}}), 1),
        ("…the host's root spelled `//` or `/.`",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["//:/host", "/.:/h2:ro"]}}}), 2),
        ("…a directory that holds the socket, and containerd's",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": [
             "/var/run:/var/run", "/run/containerd/containerd.sock:/c"]}}}), 2),
        ("…a tile (module alias) on an `auth: none` route is a door the console signs people into",
         root_without_admins(app({"port": 80, "service": "demo", "auth": "none", "module": {"id": "d", "alias": "d"}}),
                             {"services": {"demo": {"volumes": ["/var/run/docker.sock:/var/run/docker.sock"]}}}), 1),
        ("an OPEN host served by the container that mounts root is a finding, admins' app or not",
         root_in_public(dict(app({"host": "demo", "port": 80, "auth": "none"}), people="admins"),
                        {"services": {"demo": {"volumes": ["/var/run/docker.sock:/var/run/docker.sock"]}}}), 1),
        ("…but not when another service of the app serves it",
         root_in_public(app({"host": "demo", "port": 80, "auth": "none", "service": "demo-web"}),
                        {"services": {"demo": {"volumes": ["/var/run/docker.sock:/s"]}, "demo-web": {}}}), 0),
        # …and what is not root on the host
        ("a named volume called docker.sock, short and long",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": [
             "docker.sock:/x", {"type": "volume", "source": "docker.sock", "target": "/y"}]}}}), 0),
        ("an anonymous volume at the socket's path",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["/var/run/docker.sock"]}}}), 0),
        ("a bind whose target only ends in docker.sock",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["./fake:/tmp/not.docker.sock"]}}}), 0),
        ("a bind of a directory under /run that is not the socket's",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["/run/dbus:/run/dbus:ro"]}}}), 0),
        # the second reader's shapes (2026-11-10)
        ("the office's variable without braces",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["$BBOX_DOCKER_SOCK:/var/run/docker.sock:ro"]}}}),
         1),
        ("…a default that names another variable",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": [
             "${BBOX_DOCKER_SOCK:-$XDG_RUNTIME_DIR/docker.sock}:/var/run/docker.sock"]}}}), 1),
        ("…the variable's name, whatever its default",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["${BBOX_DOCKER_SOCK:-./sock}:/x"]}}}), 1),
        ("a named volume the local driver binds to the host's root",
         root_without_admins(app(sso), {"volumes": {"hostroot": {"driver_opts": {"type": "none", "o": "bind",
                                                                                 "device": "/"}}},
                                        "services": {"demo": {"volumes": ["hostroot:/host"]}}}), 1),
        ("an escaped `$$` is text, not a variable",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["./a$${X_DOCKER_SOCK}b:/x"]}}}), 0),
        # the third reader's shapes
        ("the office's variable with an EMPTY default, short and long",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": [
             "${BBOX_DOCKER_SOCK:-}:/var/run/docker.sock", "${BBOX_DOCKER_SOCK-}:/x",
             {"type": "bind", "source": "${BBOX_DOCKER_SOCK:-}", "target": "/var/run/docker.sock"}]}}}), 3),
        ("…a bare name as its default, and any variable bound onto the socket",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": [
             "${BBOX_DOCKER_SOCK:-sock}:/var/run/docker.sock", "${HOST_SOCK:-}:/var/run/docker.sock"]}}}), 2),
        ("Docker Desktop's raw socket under another name",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["/var/run/docker.sock.raw:/s"]}}}), 1),
        ("…and one named DOCKER_SOCKET",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["${DOCKER_SOCKET:-}:/x"]}}}), 1),
        ("a variable that only begins like the socket's is not it",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["${DOCKER_SOCKET_PROXY_DATA:-./proxy}:/data"]}}}),
         0),
        ("a named volume through a variable, not onto the socket, is docker's storage",
         root_without_admins(app(sso), {"services": {"demo": {"volumes": ["${DATA_VOL:-appdata}:/data"]}}}), 0),
        ("a router the compose writes on the rooted service without a sign-in is an open door",
         root_in_public(dict(app(sso), people="admins"), {"services": {"demo": {
             "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
             "labels": ["traefik.http.routers.demo-hook.rule=Host(`demo.localhost`) && Path(`/hook`)",
                        "traefik.http.routers.demo-hook.middlewares=hsts@file"]}}}), 1),
        ("…the same router with the sign-in is not",
         root_in_public(dict(app(sso), people="admins"), {"services": {"demo": {
             "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
             "labels": ["traefik.http.routers.demo-hook.rule=Host(`demo.localhost`)",
                        "traefik.http.routers.demo-hook.middlewares=authentik-admins@file,hsts@file"]}}}), 0),
    ]
    OPEN_ROOT_KNOWN[("demo", "demo-hook")] = "the self-test's declared exception"
    open_hook = {"services": {"demo": {"volumes": ["/var/run/docker.sock:/s"],
                                       "labels": ["traefik.http.routers.demo-hook.rule=Path(`/hook`)"]}}}
    cases += [
        ("…a declared exception is not a finding", root_in_public(app(sso), open_hook), 0),
        ("…and a declaration whose router is gone is one (stale)",
         stale_open_root(app(sso), {"services": {"demo": {"volumes": ["/var/run/docker.sock:/s"]}}}), 1),
        ("…a declaration whose router is still open is not", stale_open_root(app(sso), open_hook), 0),
    ]
    del OPEN_ROOT_KNOWN[("demo", "demo-hook")]
    tls = {"entrypoints": "websecure", "rule": "Host(`demo.example.com`)"}
    cases += [  # invariant 7: the pin on every websecure router, and FIRST (DGO-1595)
        ("a websecure router with hsts first is not a finding",
         missing_hsts(app(sso), doc(**{"demo-https": dict(tls, middlewares="hsts@file,authentik@file")}), "x"), 0),
        ("…one with no hsts is one",
         missing_hsts(app(sso), doc(**{"demo-https": dict(tls, middlewares="authentik@file")}), "x"), 1),
        ("…one with hsts after the sign-in is one (its 302 ends the chain first)",
         missing_hsts(app(sso), doc(**{"demo-https": dict(tls, middlewares="authentik@file,hsts@file")}), "x"), 1),
        ("…a plain-http router owes no pin",
         missing_hsts(app(sso), doc(**{"demo-http": {"entrypoints": "web", "middlewares": "authentik@file"}}), "x"), 0),
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
    mixed = app(sso, {"port": 80, "service": "demo", "auth": "none",
                      "module": {"id": "demo-rec", "alias": "rec"}})
    ok = [r["host"] for r in router_entries(mixed)] == ["demo"]
    bad += 0 if ok else 1
    print("  [%s] router_entries keeps the router row and drops the module-only row" % ("ok " if ok else "FAIL"))
    # invariant 5: bina-claude as it shipped (two unnamed emitted entries), as fixed, and the shapes it allows
    desk = {"host": "claude", "port": 3000, "service": "demo-desktop", "auth": "sso"}
    term = {"host": "claude-terminal", "port": 7681, "service": "demo", "auth": "sso"}
    five = [("two unnamed emitted entries share one router name", router_name_clashes(app(desk, term)), 1),
            ("naming the second one ends it", router_name_clashes(app(desk, dict(term, name="claude-terminal"))), 0),
            ("an entry whose labels the app writes itself is not the compiler's",
             router_name_clashes(app(dict(desk, emit_labels=False), dict(term, emit_labels=False))), 0),
            ("a module-only row (no host) has no router", router_name_clashes(app(desk, {"port": 80, "service": "demo"})), 0)]
    for name, got, want in five:
        ok = len(got) == want
        bad += 0 if ok else 1
        print("  [%s] %s (%d finding(s), want %d)" % ("ok " if ok else "FAIL", name, len(got), want))
    print("route-claim-lint self-test: %d/%d passed" % (len(cases) + 2 + len(five) - bad, len(cases) + 2 + len(five)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv[1:] else main())
