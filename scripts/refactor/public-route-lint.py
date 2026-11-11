#!/usr/bin/env python3
"""public-route-lint — gate G116: every route an office serves with no sign-in is one it says is public (DGO-1177).

    python3 scripts/refactor/public-route-lint.py             # this office's open routes, against its `public:`
    python3 scripts/refactor/public-route-lint.py --strict    # an undeclared open route fails (the next stage)
    python3 scripts/refactor/public-route-lint.py --live      # the office's live edge: every router traefik serves
    python3 scripts/refactor/public-route-lint.py --live --labels-from FILE [--sso on|off] [--config-dir DIR]
    python3 scripts/refactor/public-route-lint.py --self-test

WHY. A routing entry with `auth: none` is served with no sign-in by every office that runs its app — on a LAN
office to the LAN, on vps1 to the internet (DGO-1177 counted 9 such routes there). Nothing said which of them an
office MEANT to be open: the manifest says the app can be open, never that this office wants it so. This gate
asks each office to say it: platform.state.yaml's top-level `public:` names the open routes it accepts.

WHAT COUNTS. Every routing entry of every app this office runs — reconcile.py's own resolve() over its own
catalog and this tree's platform.state.yaml, so «runs» means what the compiler means — whose `auth` is `none`.
A route is named by its `host`, or `<app>:<port>` when it has none. The report says how many it read.

WHAT IS DECLARED. (a) The office: `public:` in platform.state.yaml, a list of those names. (b) The platform's
own sign-in, open on every office by what it is: INHERENT below, each with its reason — the page a person signs
in on cannot ask for a sign-in first.

THE STAGES (AGENTS.md rule 8: no gate held the callers of this contract, so it is staged). Now: the report
names every undeclared open route and exits 0 — each office declares its own (its own branch's state file).
--strict fails on them; it becomes the default once the offices have declared — and once it is settled where an
office's state lives for CI (.gitignore prepares to untrack platform.state.yaml; untracked, CI would read the
default state and no office's `public:`). Always a failure, at any stage:
a `public:` that is not a list of names (the declaration cannot be read), and an INHERENT entry no manifest
serves open (the gate's own table rotted).

ANTI-ROT. A `public:` name this office does not serve open is reported too: a declaration that outlived its route
is how an open door is re-opened unnoticed when a route of that name comes back.

THE LIVE EDGE (--live, stage 2, run-gates.py's live lane). The manifests are what an office COULD serve; its edge is
what it serves — every router of the running containers' labels and of traefik's file provider, including those an
app's own compose labels define (drive, authentik: emit_labels false). Each is behind the sign-in, serves nothing, is
one of the platform's own doors, or is declared in `public:` (a host it provably names, or `router:<name>`); every
other one is open and named, at the same stages. The rules — and how a rule proves its hosts — are
scripts/refactor/public_route_live.py's docstring. Run on the office's own checkout: its compiled file-provider
config (zz-serve.yaml, gitignored) is read there.

Not here: published ports (G84).
"""
import argparse
import importlib.util
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import public_route_live as live_edge  # noqa: E402

#: the platform's own sign-in: open on every office by what it is (`<app>/<route name>` → why). By the app AND the
#: name: another app that calls a route `auth` is not the sign-in, and is excused by nothing here.
INHERENT = {
    "forward-auth/signin": "the sign-in page — where a person signs in, so it cannot ask for a sign-in first",
    "authentik/auth": "the identity provider's front (its sign-in flows and OAuth endpoints) every sign-in asks",
}


def route_name(app_id, r):
    return r.get("host") or f"{app_id}:{r.get('port')}"


def judge(cat, order, state):
    """(read, open_routes, undeclared, stale, broken) for an office: `cat` the manifests by id, `order` the apps it
    runs, `state` its platform.state.yaml. `broken` are failures at every stage."""
    broken = []
    if state.get("schema_version") != 1:
        broken.append(f"platform.state.yaml schema_version {state.get('schema_version')!r} is not 1 — the compiler "
                      f"refuses this state, so nothing here is judged on it")
    declared = state.get("public", [])
    if declared is None:
        declared = []
    if not isinstance(declared, list) or not all(isinstance(x, str) and x for x in declared):
        broken.append("platform.state.yaml `public:` is not a list of route names — it cannot be read")
        declared = []
    read, open_routes = 0, []
    for aid in order:
        for r in (cat.get(aid) or {}).get("routing") or []:
            if not isinstance(r, dict):
                continue
            read += 1
            if r.get("auth") == "none":
                open_routes.append((aid, route_name(aid, r)))
    names = {n for _, n in open_routes}
    undeclared = [(aid, n) for aid, n in open_routes if f"{aid}/{n}" not in INHERENT and n not in declared]
    stale = sorted(n for n in set(declared) if n not in names)
    served_anywhere = {f"{aid}/{route_name(aid, r)}" for aid, a in cat.items() for r in (a.get("routing") or [])
                       if isinstance(r, dict) and r.get("auth") == "none"}
    broken += [f"INHERENT names «{n}», which no manifest serves with auth: none — this gate's table rotted"
               for n in sorted(INHERENT) if n not in served_anywhere]
    return read, open_routes, undeclared, stale, broken


def inherent(open_routes):
    return [(aid, n) for aid, n in open_routes if f"{aid}/{n}" in INHERENT]


def report(read, open_routes, undeclared, stale, broken, strict, out=print):
    for aid, n in undeclared:
        out(f"  open, undeclared  {n:<22} ({aid}: auth: none) — name it in platform.state.yaml `public:` if this "
            f"office means it open, or make the route auth: sso")
    for n in stale:
        out(f"  declared, not open  {n:<20} — `public:` names a route this office does not serve open: remove it")
    for b in broken:
        out(f"  BROKEN  {b}")
    head = (f"{read} routing entr(y/ies) of the apps this office runs, {len(open_routes)} served with no sign-in "
            f"({len(inherent(open_routes))} the platform's own sign-in)")
    if broken or (strict and (undeclared or stale)):
        out(f"G116 FAIL — {head}; {len(undeclared)} undeclared, {len(stale)} stale, {len(broken)} broken.")
        return 1
    if undeclared or stale:
        out(f"G116 WARN — {head}; {len(undeclared)} undeclared, {len(stale)} stale (stage 1 of DGO-1177: "
            f"--strict fails on these).")
        return 0
    out(f"G116 PASS — {head}; every one declared.")
    return 0


def this_office():
    """(catalog, the apps this office runs, its state) — reconcile.py's own reading, never a copy of it; the state
    read as load_state reads it, without load_state's ensure_state (a gate writes nothing)."""
    spec = importlib.util.spec_from_file_location("reconcile_g116", REPO / "platform" / "manager" / "reconcile.py")
    rc = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_g116"] = rc
    spec.loader.exec_module(rc)
    state = rc.yaml.safe_load(rc.STATE.read_text(encoding="utf-8")) if rc.STATE.is_file() else None
    if not isinstance(state, dict):
        state = rc.yaml.safe_load(rc.DEFAULT_STATE.read_text(encoding="utf-8")) or {}
    apps = state.get("apps") or {}
    for old_id, new_id in rc.LEGACY_APP_IDS.items():   # as load_state renames them
        if isinstance(apps, dict) and old_id in apps and new_id not in apps:
            apps[new_id] = apps.pop(old_id)
    cat = rc.load_catalog()
    order, _ = rc.resolve(cat, state)
    return cat, order, state


def self_test():
    lines, ok = [], True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(("  [ok ] " if cond else "  [FAIL] ") + name)

    cat = {
        "forward-auth": {"routing": [{"host": "signin", "auth": "none"}]},
        "authentik": {"routing": [{"host": "auth", "auth": "none"}]},
        "meet": {"routing": [{"host": "meet", "auth": "none"}, {"host": "meet-admin"}]},
        "drive": {"routing": [{"port": 8975, "auth": "none"}]},
        "off": {"routing": [{"host": "later", "auth": "none"}]},
        "impostor": {"routing": [{"host": "auth", "auth": "none"}]},
    }
    order = ["forward-auth", "authentik", "meet", "drive"]
    v1 = {"schema_version": 1}
    r = judge(cat, order, {**v1, "public": ["meet", "drive:8975"]})
    check("declared open routes and the sign-in pass", r[2] == [] and r[3] == [] and r[4] == [] and r[0] == 5)
    r = judge(cat, order, dict(v1))
    check("an undeclared open route is named, by host or by app:port",
          [n for _, n in r[2]] == ["meet", "drive:8975"] and report(*r, strict=False, out=lines.append) == 0
          and report(*r, strict=True, out=lines.append) == 1)
    r = judge(cat, order, {**v1, "public": ["meet", "drive:8975", "later"]})
    check("a declaration of a route this office does not run is stale, and --strict fails on it alone",
          r[3] == ["later"] and report(*r, strict=False, out=lines.append) == 0
          and report(*r, strict=True, out=lines.append) == 1)
    r = judge(cat, order, {**v1, "public": "meet"})
    check("a `public:` that is not a list is broken at every stage",
          r[4] and report(*r, strict=False, out=lines.append) == 1)
    r = judge(cat, order, {**v1, "public": [{"host": "meet"}]})
    check("a `public:` of things that are not names is broken, not a crash", r[4] and r[3] == [])
    r = judge(cat, order, {**v1, "public": None})
    check("`public:` with no value is an empty list", r[4] == [] and [n for _, n in r[2]] == ["meet", "drive:8975"])
    r = judge({k: v for k, v in cat.items() if k not in ("authentik", "impostor")}, ["forward-auth"], dict(v1))
    check("an INHERENT name no manifest serves open is the table's rot", any("«authentik/auth»" in b for b in r[4]))
    r = judge(cat, ["meet"], dict(v1))
    check("the sign-in's apps in the catalog but not run here are no rot", r[4] == [])
    r = judge(cat, ["forward-auth", "impostor"], dict(v1))
    check("another app's route named like the sign-in is not excused", [n for _, n in r[2]] == ["auth"])
    r = judge(cat, order, {"schema_version": 2, "public": ["meet", "drive:8975"]})
    check("a state the compiler refuses (schema_version) is broken", any("schema_version" in b for b in r[4]))

    # ── the live edge (public_route_live) ──
    L = live_edge
    check("live: a rule proves its hosts only when every || branch names one, with no !, regexp or v2 Host list",
          L.provable_hosts("Host(`m.x`) || HostRegexp(`.+`)") is None and L.provable_hosts("!Host(`m.x`)") is None
          and L.provable_hosts("Host(`m.x`) || PathPrefix(`/admin`)") is None
          and L.provable_hosts("Host(`a`,`b`)") is None and L.provable_hosts("") is None
          and L.provable_hosts("Host(`m.x`) && PathPrefix(`/p`)") == ["m.x"]
          and L.provable_hosts("(Host(`a`) || Host(`b`)) && PathPrefix(`/p`)") == ["a", "b"])

    def lab(name, svc, enable=True, middlewares=None, **routers):
        labels = {"traefik.enable": "true" if enable else "false", "com.docker.compose.service": svc}
        for r, (rule, mids, service) in routers.items():
            if rule:
                labels[f"traefik.http.routers.{r}.rule"] = rule
            if mids:
                labels[f"traefik.http.routers.{r}.middlewares"] = mids
            if service:
                labels[f"traefik.http.routers.{r}.service"] = service
            labels.setdefault(f"traefik.http.routers.{r}.entrypoints", "websecure")
        for k, v in (middlewares or {}).items():
            labels[k] = v
        return f"/{name} " + json.dumps(labels)

    def buckets(lines_, declared=(), sso_on=True):
        got = L.judge(L.from_labels(lines_), list(declared), sso_on=sso_on)
        return {k: sorted(r["name"] for r in v) for k, v in got.items()}

    lines_ = [lab("traefik-o", "traefik-deployment", enable=False),
              lab("console-o", "console", console=("Host(`console.o`)", "authentik@file", "")),
              lab("bare-o", "myapp", bare=("Host(`bare.o`)", "authentik", "")),
              lab("forward-auth-o", "forward-auth", **{"forward-auth-https": ("Host(`auth.o`)", "", "")}),
              lab("myapp-o", "myapp", **{"forward-auth-x": ("Host(`myapp.o`)", "", "")}),
              lab("proxy-o", "forward-auth-proxy", **{"forward-auth-y": ("Host(`p.o`)", "", "")}),
              lab("meet-o", "meet", meet=("Host(`meet.o`)", "", ""), share=("Host(`drive.o`) && PathPrefix(`/s`)", "", "")),
              lab("apex-o", "console", apex=("Host(`o`)", "", "noop@internal"),
                  page=("Host(`err.o`)", "oops", "noop@internal"),
                  middlewares={"traefik.http.middlewares.oops.errors.service": "console"}),
              lab("lone-o", "lone"),
              lab("lan-signin-o", "lan-signin", lanc=("Host(`lan.o`)", "lan-auth", ""),
                  middlewares={"traefik.http.middlewares.lan-auth.forwardauth.address": "http://lan-signin"})]
    b = buckets(lines_, ["meet", "router:share"])
    fake = lab("fake-o", "myapp", middlewares={"traefik.http.middlewares.authentik.headers.customrequestheaders.X": "y"})
    check("live: a bare `authentik` on a label router is authentik@docker — never the sign-in: dropped while no "
          "container defines it, open when an app defines its own",
          "bare" not in b["signed"] and "bare" in b["dropped"] and "bare" in buckets(lines_ + [fake], ["meet"])["open"])
    check("live: the signed, a door by its exact compose service, a declared host and a router: name are told apart",
          b["signed"] == ["console", "lanc"] and b["doors"] == ["forward-auth-https"] and b["declared"] == ["meet", "share"])
    check("live: a router named like a door on another service (or a service named like one) is open",
          "forward-auth-x" in b["open"] and "forward-auth-y" in b["open"])
    check("live: noop@internal serves nothing — unless an errors middleware fetches a page for it",
          b["nothing"] == ["apex"] and "page" in b["open"])
    check("live: an enabled container with no router is served under traefik's default rule — open", "lone-o" in b["open"])
    check("live: with SSO off, authentik@file stamps a user and is no sign-in",
          "console" in buckets(lines_, ["meet"], sso_on=False)["open"])
    impostor = lab("evil-o", "evil", middlewares={"traefik.http.middlewares.lan-auth.headers.customrequestheaders.X": "y"})
    check("live: lan-auth@docker is the sign-in only while lan-signin is the one container defining it",
          "lanc" in buckets(lines_ + [impostor])["open"])
    ghost = lab("remote-o", "dgo-extend", gone=("Host(`gone.o`)", "lan-auth-admins@docker", ""))
    check("live: a router naming a docker middleware no container defines is dropped (a fault, not open)",
          "gone" in buckets(lines_ + [ghost])["dropped"] and "gone" not in buckets(lines_ + [ghost])["open"])
    redis = '/redis-o ' + json.dumps({"traefik.enable": "true", "com.docker.compose.service": "redis",
                                      "traefik.tcp.routers.redis.rule": "HostSNI(`*`)",
                                      "traefik.tcp.routers.redis.middlewares": "redis-ipallowlist",
                                      "traefik.tcp.middlewares.redis-ipallowlist.ipallowlist.sourcerange": "10.0.0.0/8"})
    wide = redis.replace("10.0.0.0/8", "0.0.0.0/0")
    check("live: a TCP router behind an IP allowlist is fenced (its definition read, not a fault); 0.0.0.0/0 is open",
          buckets([redis])["fenced"] == ["redis"] and buckets([redis])["dropped"] == []
          and buckets([wide])["open"] == ["redis"])
    tcp = '/turn-o ' + json.dumps({"traefik.enable": "true", "com.docker.compose.service": "meet",
                                    "traefik.tcp.routers.turn.rule": "HostSNI(`*`)"})
    check("live: a TCP router is open unless its name is declared",
          "turn" in buckets([tcp])["open"] and "turn" in buckets([tcp], ["router:turn"])["declared"])
    out_ = []
    empty = L.Edge()
    br = L.judge(empty, [])
    check("live: reading nothing fails — no traefik among the containers, no router from the labels, no config dir",
          L.report(br, empty, 0, False, True, True, [], strict=False, out=out_.append) == 1
          and L.report(br, empty, 0, True, True, True, [], strict=False, out=out_.append) == 1
          and L.report(br, empty, 3, True, False, True, [], strict=False, out=out_.append) == 1)
    full_edge = L.from_labels(lines_)
    full = L.judge(full_edge, ["meet"], sso_on=True)
    check("live: open (or dropped) routers warn now, fail under --strict; an unreadable `public:` fails",
          L.report(full, full_edge, 9, True, True, True, ["meet"], strict=False, out=out_.append) == 0
          and L.report(full, full_edge, 9, True, True, True, ["meet"], strict=True, out=out_.append) == 1
          and L.report(full, full_edge, 9, True, True, True, None, strict=False, out=out_.append) == 1)
    import tempfile
    import yaml
    with tempfile.TemporaryDirectory() as d:
        pathlib.Path(d, "zz-serve.yaml").write_text(
            "http:\n  routers:\n    peer:\n      rule: Host(`peer.o`)\n      middlewares: [authentik]\n"
            "    open:\n      rule: Host(`open.o`)\n", encoding="utf-8")
        pathlib.Path(d, "more.yml").write_text("http:\n  routers:\n    yml:\n      rule: Host(`yml.o`)\n", encoding="utf-8")
        pathlib.Path(d, "more.toml").write_text('[http.routers.tml]\nrule = "Host(`tml.o`)"\n', encoding="utf-8")
        pathlib.Path(d, "tmpl.yaml").write_text("http:\n{{- range $x := list 1 }}\n", encoding="utf-8")
        pathlib.Path(d, "sub").mkdir()
        pathlib.Path(d, "sub", "deep.YAML").write_text("udp:\n  routers:\n    voice:\n      service: v\n", encoding="utf-8")
        pathlib.Path(d, "bad.yaml").write_text("http:\n  routers: [a]\n  middlewares: [b]\n", encoding="utf-8")
        got = L.judge(L.from_files(d, yaml.safe_load), [], sso_on=True)
        check("live: the file provider — yaml, yml, toml and a .YAML below, a bare name there is @file, a template "
              "skipped, a udp router read, a malformed section no raise",
              [r["name"] for r in got["signed"]] == ["peer"]
              and sorted(r["name"] for r in got["open"]) == ["open", "tml", "voice", "yml"])
        pathlib.Path(d, "00-a.yaml").write_text("http:\n  middlewares:\n    authentik:\n      headers:\n"
                                                "        customRequestHeaders: {X-authentik-username: akadmin}\n",
                                                encoding="utf-8")
        got = L.judge(L.from_files(d, yaml.safe_load), [], sso_on=True)
        check("live: a file that defines `authentik` itself (traefik keeps the first) — authentik@file is no sign-in",
              "peer" in [r["name"] for r in got["open"]])
    check("live: a nested || without a Host proves nothing",
          L.provable_hosts("(Host(`meet.o`) || PathPrefix(`/`)) && Method(`GET`)") is None
          and L.provable_hosts("((Host(`a`) || Host(`b`))) && PathPrefix(`/p`)") == ["a", "b"])
    check("live: an allowlist admits everyone in any /0 spelling; a range that does not parse is no fence",
          L.everyone(["10.0.0.1/0"]) is True and L.everyone(["::0/0"]) is True and L.everyone(["0::0/0"]) is True
          and L.everyone(["10.0.0.0/8", "fd00::/8"]) is False and L.everyone(["not-a-range"]) is None)
    gobool = '/gb-o ' + json.dumps({"traefik.enable": "1", "com.docker.compose.service": "gb",
                                    "Traefik.HTTP.Routers.gb.Rule": "Host(`gb.o`)"})
    check("live: traefik.enable is read as a Go bool and label keys case-insensitively", buckets([gobool])["open"] == ["gb"])
    chained = lab("ch-o", "console", hop=("Host(`hop.o`)", "hops", "noop@internal"),
                  middlewares={"traefik.http.middlewares.hops.chain.middlewares": "oops"})
    check("live: noop@internal behind a chain is not «serves nothing»", "hop" in buckets([chained])["open"])
    check("live: a rule's double-quoted strings are strings — a `||` inside one splits nothing, a Host in one is read",
          L.provable_hosts('Host(`a.o`) && Header(`X`, "`") || PathRegexp("`|.*")') is None
          and L.provable_hosts('Host("q.o") && PathPrefix("/x")') == ["q.o"])
    check("live: ranges that TOGETHER admit everyone are no fence (halves, an IPv4-mapped /96)",
          L.everyone(["0.0.0.0/1", "128.0.0.0/1"]) is True and L.everyone(["::ffff:0.0.0.0/96"]) is True
          and L.everyone(["::ffff:10.0.0.0/104"]) is False and L.everyone([]) is None)
    plug = lab("pl-o", "console", gate=("Host(`gate.o`)", "plug", "noop@internal"),
               middlewares={"traefik.http.middlewares.plug.plugin.x.y": "z"})
    unknown = lab("un-o", "console", ghostmw=("Host(`gm.o`)", "lan-name@file", "noop@internal"))
    check("live: noop@internal «serves nothing» only behind middlewares of kinds that answer from the request alone",
          "gate" in buckets([plug])["open"] and "ghostmw" in buckets([unknown])["open"])
    tcp_only = '/to-o ' + json.dumps({"traefik.enable": "true", "com.docker.compose.service": "to",
                                       "traefik.tcp.routers.t.rule": "HostSNI(`*`)",
                                       "traefik.http.services.to.loadbalancer.server.port": "80"})
    check("live: a container with only a tcp router but http labels also gets traefik's default http router",
          "to-o" in buckets([tcp_only])["open"])
    with tempfile.TemporaryDirectory() as d:
        pathlib.Path(d, "00-x.yaml").write_text("HTTP:\n  Middlewares:\n    authentik:\n      Headers: {}\n"
                                                "    wide:\n      IPAllowList:\n        SourceRange: [0.0.0.0/0]\n"
                                                "  Routers:\n    seen:\n      Rule: Host(`seen.o`)\n", encoding="utf-8")
        pathlib.Path(d, "zz.yaml").write_text("http:\n  routers:\n    peer:\n      rule: Host(`peer.o`)\n"
                                              "      middlewares: [authentik]\n    w:\n      rule: Host(`w.o`)\n"
                                              "      middlewares: [wide]\n", encoding="utf-8")
        got = L.judge(L.from_files(d, yaml.safe_load), [], sso_on=True)
        names = {k: sorted(r["name"] for r in v) for k, v in got.items()}
        check("live: a file's keys are read in any case (HTTP, Middlewares, SourceRange, Routers, Rule)",
              names["open"] == ["peer", "seen", "w"] and names["signed"] == [] and names["fenced"] == [])
        pathlib.Path(d, "00-a-tmpl.yaml").write_text("http:\n{{- x }}\n", encoding="utf-8")
        pathlib.Path(d, "zz.yaml").write_text("http:\n  middlewares:\n    f:\n      ipAllowList:\n"
                                              "        sourceRange: [10.0.0.0/8]\n  routers:\n    fr:\n"
                                              "      rule: Host(`fr.o`)\n      middlewares: [f]\n", encoding="utf-8")
        got = L.judge(L.from_files(d, yaml.safe_load), [], sso_on=True)
        check("live: a file's fence is not believed while a template was skipped (it may define the name first)",
              [r["name"] for r in got["fenced"]] == [] and "fr" in [r["name"] for r in got["open"]])
    check("live: an unknown SSO counts OFF", "console" in buckets(lines_, ["meet"], sso_on=False)["open"]
          and "console" in [r["name"] for r in L.judge(L.from_labels(lines_), ["meet"])["open"]])
    check("live: every door has its reason", all(len(v) > 20 for v in L.DOORS.values()))
    print(f"public-route-lint self-test: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--live", action="store_true", help="the office's live edge, not the manifests")
    ap.add_argument("--labels-from", metavar="FILE", help="with --live: captured `docker inspect` label lines")
    ap.add_argument("--sso", choices=("on", "off"), help="with --labels-from: the edge's SSO (captures carry no env)")
    ap.add_argument("--config-dir", metavar="DIR", help="with --live: traefik's file-provider directory "
                    "(default: this checkout's platform-base/traefik/config, as the office runs it)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    cat, order, state = this_office()
    if not a.live:
        return report(*judge(cat, order, state), strict=a.strict)
    return check_live(state, a.labels_from, a.sso, a.config_dir, a.strict)


def declared_public(state):
    """The office's `public:` as a list of names, or None when it cannot be read."""
    d = state.get("public", [])
    d = [] if d is None else d
    return d if isinstance(d, list) and all(isinstance(x, str) and x for x in d) else None


def check_live(state, labels_from, sso, config_dir, strict, out=print):
    import subprocess
    try:
        lines, sso_on, traefik_read = live_edge.read_edge(labels_from)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
        out(f"G116 FAIL (live) — the edge could not be read: {e}")
        return 1
    if sso is not None:
        sso_on = sso == "on"
    import yaml                                   # reconcile.py's own dependency, there wherever this runs
    edge = live_edge.from_labels(lines)
    labelled = len(edge.routers)
    config = pathlib.Path(config_dir) if config_dir else REPO / "platform-base" / "traefik" / "config"
    if config.is_dir():
        live_edge.from_files(config, yaml.safe_load, edge)
    declared = declared_public(state)
    buckets = live_edge.judge(edge, declared or [], sso_on=sso_on is True)   # unknown SSO counts OFF
    return live_edge.report(buckets, edge, labelled, traefik_read, config.is_dir(), sso_on, declared, strict, out=out)


if __name__ == "__main__":
    sys.exit(main())
