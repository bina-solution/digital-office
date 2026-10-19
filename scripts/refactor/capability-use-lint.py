#!/usr/bin/env python3
"""capability-use-lint — gate G25: a declared capability must actually be CONSUMED, and a consumed
one must actually EXIST.

    python3 scripts/refactor/capability-use-lint.py
    python3 scripts/refactor/capability-use-lint.py --strict   # also fail on undeclared own-instances

WHY THIS GATE EXISTS

The capability graph is the thing this whole platform is organised around. The compiler resolves it,
orders bring-up by it, refuses ambiguous providers because of it, and every layering rule is stated
in terms of it. All of that assumes a declaration means something.

Measured on the running stack, 2026-07-29, the single most important edge in the graph was decorative:

    authentik  (L1)  use: [ sql (requires) ]   ->  AUTHENTIK_POSTGRESQL__HOST: authentik-postgres
    n8n        (L2)  use: [ sql (requires) ]   ->  DB_POSTGRESDB_HOST=n8n-postgres
    glitchtip  (L2)  use: [ sql (requires) ]   ->  glitchtip-postgres

Three apps declared they require the platform's `sql` capability. The resolver dutifully pulled the
`postgres` app into the closure and started it first. Then all three connected to a Postgres of their
own — FOUR servers across THREE major versions (15.8, 16, 17) where the graph says there is one.
Cost: 3 extra containers, ~325 MB of RAM, 2 extra base images in the shipped artifact, and three
separate patch and backup stories.

Nothing caught it, because nothing checks it. `plan` prints "postgres: pulled in as provider of 'sql'
for authentik" and that line is true — the app WAS pulled in. Whether anyone then talked to it was
never anybody's job to verify.

That the shape works is proven in-tree by the `kv` capability: both authentik and n8n set
AUTHENTIK_REDIS__HOST / QUEUE_BULL_REDIS_HOST to `redis`, the layer-1 provider. One server, two
consumers. `sql` is the outlier, not the norm — which is exactly why a gate can hold the line.

WHAT IT CHECKS

An app is in violation when it does BOTH of these:

  1. declares `use: [{capability: X}]`, and
  2. ships, in its own compose, a service whose IMAGE is the same software family as X's provider.

Nothing else. The first draft of this gate asked the looser question "does the consumer's compose
mention the provider's host?" and produced 25 findings of which 22 were false: apps reach their
providers through .env values the compiler renders, and through generated overlays
(connections.override.yml injects the credential broker into apitools and indox without either
compose naming it). stage-control.py had already learned exactly this, and says so:

    Read from the compiled compose, not from the source docker-compose.yml files. Globbing the
    sources missed two whole categories, because a service's mounts are not all declared in its
    own compose file.

The image-family test needs no such reading. `supabase/postgres:15.8.1.085` and `postgres:16-alpine`
are both the `postgres` family; an app that requires `sql` and runs one of those is running its own
database, whatever its environment happens to say. It is a narrow question with an unambiguous
answer, which is the only kind a gate should ask.

The same comparison catches the mirror-image bug for free: a service running a provider's software
while declaring no use[] entry for that capability at all. That is reported as an UNDECLARED
instance rather than a decorative declaration, because the graph is equally wrong either way.

A JOB IS NOT AN INSTANCE. One kind of service carries the provider's image and runs none of it: a
one-shot job that is told never to restart and whose entrypoint is replaced. `chat-relay-init`
runs `psql` out of `supabase/postgres` to create the relay's database ON the platform's cluster.
That is the opposite of an own instance — it is the app consuming the capability — so such a
service is never counted as one. What it does prove is the use: an app with a client job for X and
no `use: X` is talking to a provider the graph does not know it needs (chat did, until 2026-10-07;
`--strict` refuses it). And it is why this gate read red in CI with a message that named the wrong
fault, while `scripts/ci/gates.sh` ran it without `--strict` and showed it green.

THE MIRROR IMAGE: A USE[] NOBODY PROVIDES

Measured 2026-10-09: `apps/bina-ds/app.json` was edited to `"capability": "notifications"` — the
provider's real name is `notify` — and `python3 platform/manager/reconcile.py validate` answered
`OK — 41 manifest(s) valid` without a word. Nothing was broken by it, because nothing read it: the
compiler resolves providers only inside `resolve()`, which walks the ENABLED apps and only the HARD
strengths (`requires`/`requisite`/`binds_to`). 35 of this repo's 91 declared uses are `wants`, so for
those not even `bbox plan` on an enabled app ever looks at the name. A `use` naming something nobody
provides is therefore not a dependency at all — it is a sentence the graph never reads, and the app
that wrote it goes looking at runtime for a provider that was never there.

The rule is the exact converse of the one above: every `use[].capability` must equal some manifest's
`capabilities[].name`, across `apps/` AND `platform-base/`. The platform's own providers are manifests
too — traefik's `edge`, authentik's `identity`/`forward-auth`, the `sql`/`kv`/`secrets` substrate — so
they are FOUND, not waived; PLATFORM_CAPABILITIES below is empty for that reason and is not a blanket
"ignore what I do not recognise". It holds for every app whether or not it is enabled, which is the
point: an app sitting in the gallery is exactly the one no resolver ever walks.

WHAT IT DOES NOT DO

It does not forbid an app from running its own store. Some genuinely must — an embedded database, a
cache with incompatible eviction semantics, an upstream that hardcodes its own migrations. The point
is not to prevent that; it is to make it a DECISION IN THE MANIFEST rather than an accident in a
compose file nobody re-reads:

    "use": [{ "capability": "sql", "own_instance": true,
              "reason": "authentik's migrations assume exclusive ownership of the cluster" }]

Then `bbox plan` can print it, an operator can see it, and a reviewer can argue with it. An app that
declares `sql` and quietly runs its own is the only thing this gate refuses.
"""
import argparse
import json
import pathlib
import sys

try:
    import yaml
except ImportError:
    sys.exit("capability-use-lint: PyYAML required")

REPO = pathlib.Path(__file__).resolve().parents[2]
ROOTS = (REPO / "platform-base", REPO / "apps")

NL = "\n"


def family(image):
    """The software family of an image reference, ignoring registry, namespace and tag.

        supabase/postgres:15.8.1.085       -> postgres
        postgres:16-alpine                 -> postgres
        ghcr.io/goauthentik/server:2024.12 -> server
        redis:7-alpine                     -> redis

    Namespace is dropped on purpose: `supabase/postgres` and plain `postgres` are the same database
    with different extensions baked in, and treating them as different is precisely the mistake that
    let four Postgres servers accumulate. Tag is dropped for the same reason — three MAJOR versions
    of one piece of software is a worse problem than one, not a different problem.
    """
    ref = (image or "").strip()
    if not ref or ref.startswith("$"):
        return ""                       # fully variable image ref — nothing to compare
    ref = ref.split("@", 1)[0]          # drop any digest
    name = ref.rsplit("/", 1)[-1]       # drop registry + namespace
    return name.split(":", 1)[0].lower()


# Interchangeable implementations of one capability. valkey is a redis fork speaking the same
# protocol; treating them as unrelated would let an app dodge this gate by switching fork.
ALIASES = {"valkey": "redis", "keydb": "redis", "mariadb": "mysql"}


def fam(image):
    return ALIASES.get(family(image), family(image))


# Capabilities served by something OUTSIDE this catalog, waived BY NAME with the reason. It is empty
# and must stay that way for as long as every provider is a manifest: the enumeration below already
# spans apps/ + platform-base/, which is where the platform's own substrate (sql, kv, secrets, edge,
# identity, forward-auth, ui-kit) declares itself. An entry here is a deliberate exception with an
# owner and a reason — never a wildcard, because a wildcard would delete the rule this gate exists to
# hold. Adding one is the same decision as `own_instance`: say why, in the manifest's own voice.
PLATFORM_CAPABILITIES = {}


def one_shot(svc):
    """A job, not a server: told never to restart AND given another entrypoint. (`restart: no`
    unquoted is YAML's false; both spellings are the same instruction.)"""
    return svc.get("restart") in ("no", False) and bool(svc.get("entrypoint"))


def services(app, jobs=False):
    """{service name: image family} for the app's own compose — the services that RUN the image,
    or with `jobs=True` the one-shot jobs that only borrow it for the client inside.

    Services with a `build:` and no `image:` are skipped: a first-party build is this repo's own
    code, not a datastore an app quietly brought along, and guessing at its contents would be the
    kind of heuristic this gate exists to avoid.
    """
    comp = app.get("compose")
    if not comp:
        return {}
    try:
        doc = yaml.safe_load((app["_dir"] / comp).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    out = {}
    for name, svc in (doc.get("services") or {}).items():
        if isinstance(svc, dict) and svc.get("image") and one_shot(svc) == jobs:
            f = fam(svc["image"])
            if f:
                out[name] = f
    return out


def service_names(name, svc):
    """Every name a compose service answers to on the network.

    Service name, container_name, hostname, and any explicit network aliases. A capability endpoint
    may legitimately use any of them, and this repo uses three different ones for a single service.
    A `${VAR}` suffix on container_name is trimmed: `supabase-db-${DEPLOYMENT_NAME}` is still the
    supabase-db service, and comparing the un-interpolated string would never match anything.
    """
    out = {name}
    for key in ("container_name", "hostname"):
        v = svc.get(key)
        if v:
            v = str(v)
            out.add(v)
            out.add(v.split("-${", 1)[0].split("${", 1)[0].rstrip("-"))
    nets = svc.get("networks")
    if isinstance(nets, dict):
        for n in nets.values():
            if isinstance(n, dict):
                out.update(str(a) for a in (n.get("aliases") or []))
    return {o for o in out if o}


def load_catalog():
    cat = {}
    for root in ROOTS:
        if not root.exists():
            continue
        for m in sorted(root.glob("*/app.json")):
            try:
                a = json.loads(m.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                sys.exit(f"capability-use-lint: {m.relative_to(REPO)}: invalid JSON: {e}")
            a["_dir"] = m.parent
            cat[a.get("id") or m.parent.name] = a
    return cat


def capability_families(cat):
    """capability -> {image families that PROVIDE it}.

    The family must come from the ONE service that actually serves the capability, found through
    the capability's own `endpoint` host. The obvious shortcut — union every family in the
    provider's compose — is wrong, and wrong in the direction that makes the gate useless: glitchtip
    provides `error-tracking` and also runs a postgres and a redis sidecar, so `error-tracking`
    would inherit the `postgres` family, and then EVERY app with a postgres of its own would appear
    to be running its own error-tracker. That draft reported 26 findings, 22 of them noise.

    A service is reachable under FOUR different names in this repo and the endpoint may use any of
    them, so all four are indexed. The postgres app alone demonstrates three: its service is `db`,
    its container_name is `supabase-db-${DEPLOYMENT_NAME}`, and its hostname — which is what the
    `sql` endpoint actually names — is `supabase-db`. Indexing only the first two made this gate
    report a clean PASS while three apps were visibly running their own database, which is the worst
    outcome a gate can have.
    """
    out = {}
    for aid, a in cat.items():
        comp = a.get("compose")
        if not comp:
            continue
        try:
            doc = yaml.safe_load((a["_dir"] / comp).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        svcs = (doc.get("services") or {})
        # host -> family, for every name the host could be written as
        by_host = {}
        for name, svc in svcs.items():
            if not isinstance(svc, dict) or not svc.get("image"):
                continue
            f = fam(svc["image"])
            if not f:
                continue
            for alias in service_names(name, svc):
                by_host[alias] = f
        for c in a.get("capabilities", []):
            ep, name = c.get("endpoint"), c.get("name")
            if not (ep and name):
                continue          # abstract capability (forward-auth, automation-stdlib) — no image
            host = ep.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0]
            f = by_host.get(host)
            if f:
                out.setdefault(name, set()).add(f)
    return out


def unsatisfied(cat, waivers=None):
    """[(app id, capability, strength, manifest path)] for every use[] whose capability NO manifest
    provides and no waiver names — the converse of the rule above, and the one the compiler does not
    ask: `resolve()` walks enabled apps and hard strengths only, and `validate` never asks at all.

    The provider set is every `capabilities[].name` in the catalog, apps/ and platform-base/ alike,
    regardless of a provider's `endpoint`: an abstract capability (forward-auth, automation-stdlib)
    is still provided by a manifest, and requiring an endpoint here would refuse those.
    """
    if waivers is None:
        waivers = PLATFORM_CAPABILITIES
    provided = {c["name"] for a in cat.values() for c in a.get("capabilities", []) if c.get("name")}
    out = []
    for aid in sorted(cat):
        a = cat[aid]
        for u in a.get("use", []):
            cap = u.get("capability")
            if not cap or cap in provided or cap in waivers:
                continue
            out.append((aid, cap, u.get("strength", "requires"),
                        str((a["_dir"] / "app.json").relative_to(REPO))))
    return out


def fake(aid, caps=(), uses=()):
    """A manifest small enough to assert on: just the two halves the satisfaction rule reads."""
    return {"id": aid, "_dir": REPO / "apps" / aid,
            "capabilities": [{"name": c} for c in caps],
            "use": [{"capability": c} for c in uses]}


def self_test() -> int:
    server = {"image": "postgres:16", "restart": "unless-stopped", "command": ["postgres", "-c", "x=1"]}
    job = {"image": "supabase/postgres:15.8.1.085", "restart": "no", "entrypoint": ["/bin/bash", "-c"]}
    # the failing shape the accident produced: `notifications` where the provider says `notify`.
    # (`notify` is a `wants`, so the compiler's own resolve() never looked at it either.)
    provided = {"notifications": fake("notifications", caps=("notify",))}
    typo = {**provided, "bina-ds": fake("bina-ds", uses=("notifications",))}
    good = {**provided, "bina-ds": fake("bina-ds", uses=("notify",))}
    waived = fake("edge-client", uses=("external-thing",))
    cases = [
        ("a database with flags on its command is a server", one_shot(server), False),
        ("never restarted AND another entrypoint: a job", one_shot(job), True),
        ("`restart: no` unquoted (YAML false) is the same instruction", one_shot(dict(job, restart=False)), True),
        ("a job that keeps the image's entrypoint still runs the server", one_shot({"image": "redis:7", "restart": "no"}), False),
        ("another entrypoint but restarted: a server with a wrapper", one_shot(dict(job, restart="always")), False),
        ("namespace and tag do not make a different database", fam("supabase/postgres:15.8.1.085"), "postgres"),
        ("a fork speaking the same protocol is the same family", fam("valkey/valkey:8"), "redis"),
        ("a use[] a manifest provides is satisfied", unsatisfied(good), []),
        ("a use[] NOBODY provides is refused, by name and manifest",
         unsatisfied(typo), [("bina-ds", "notifications", "requires", "apps/bina-ds/app.json")]),
        ("a use[] a waiver names is satisfied", unsatisfied({"x": waived}, {"external-thing": "why"}), []),
        ("a waiver is by name, never a blanket", unsatisfied(typo, {"external-thing": "why"}) != [], True),
    ]
    bad = 0
    for name, got, want in cases:
        bad += got != want
        print("  [%s] %s (got %r, want %r)" % ("ok " if got == want else "FAIL", name, got, want))
    print("capability-use-lint self-test: %d/%d passed" % (len(cases) - bad, len(cases)))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="also fail on an UNDECLARED own instance or use, and on own_instance with no reason")
    ap.add_argument("--self-test", action="store_true", help="prove the job/server and family rules")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    cat = load_catalog()
    capfam = capability_families(cat)
    unmatched = unsatisfied(cat)
    fam_cap = {}
    for cap, fams in capfam.items():
        for f in fams:
            fam_cap.setdefault(f, set()).add(cap)

    violations, declared, undeclared, clients = [], [], [], []

    for aid in sorted(cat):
        a = cat[aid]
        mine = services(a)
        jobs = services(a, jobs=True)
        if not (mine or jobs):
            continue
        provides = {c["name"] for c in a.get("capabilities", []) if c.get("name")}
        uses = {u["capability"]: u for u in a.get("use", []) if u.get("capability")}

        for cap, u in sorted(uses.items()):
            want = capfam.get(cap) or set()
            hits = sorted(s for s, f in mine.items() if f in want)
            if not hits:
                continue                       # runs nothing of the provider's family — fine
            if u.get("own_instance"):
                declared.append((aid, cap, hits, u.get("reason") or ""))
            else:
                violations.append((aid, cap, hits, sorted(want)))

        for svc, f in sorted(mine.items()):
            for cap in sorted(fam_cap.get(f, ())):
                if cap in uses or cap in provides:
                    continue
                undeclared.append((aid, cap, svc, f))
        for svc, f in sorted(jobs.items()):
            clients += [(aid, cap, svc, f) for cap in sorted(fam_cap.get(f, ()))
                        if cap not in uses and cap not in provides]

    print("CAPABILITY CONSUMPTION (G25)")
    print("-" * 78)
    for aid, cap, hits, reason in declared:
        note = f" - {reason}" if reason else "  [NO REASON GIVEN]"
        print(f"  own instance, declared    {aid}/{cap} ({', '.join(hits)}){note}")
    for aid, cap, svc, f in undeclared:
        print(f"  own instance, UNDECLARED  {aid}: '{svc}' runs {f}, which provides '{cap}' - "
              f"but {aid} declares no use['{cap}']")
    for aid, cap, svc, f in clients:
        print(f"  use, UNDECLARED           {aid}: '{svc}' is a one-shot {f} client, so {aid} "
              f"consumes '{cap}' - but declares no use['{cap}']")
    for aid, cap, hits, want in violations:
        print(f"  DECORATIVE                {aid}: declares use['{cap}'] and runs its own "
              f"{'/'.join(want)}: {', '.join(hits)}")
    for aid, cap, strength, path in unmatched:
        print(f"  use, UNSATISFIED          {aid}: use['{cap}'] ({strength}) in {path} — no manifest "
              f"provides '{cap}'")
    if not (declared or undeclared or clients or violations or unmatched):
        print(f"  {len(cat)} app(s) checked — nothing to report.")
    print("-" * 78)

    bad = len(violations) + len(unmatched)
    if args.strict:
        bad += len(undeclared) + len(clients) + sum(1 for *_, r in declared if not r)

    if not bad:
        print(NL + f"G25 PASS - {len(cat)} app(s): no app declares a capability and then runs its own,"
                   f" and every use[] is provided by a manifest.")
        return 0

    extra = ((f", {len(undeclared)} undeclared instance(s)" if args.strict and undeclared else "")
             + (f", {len(clients)} undeclared use(s)" if args.strict and clients else ""))
    print(NL + f"G25 FAIL - {len(violations)} decorative declaration(s){extra}"
               f"{f', {len(unmatched)} unsatisfied use(s)' if unmatched else ''}.", file=sys.stderr)
    if unmatched:
        print("""
These declare a use[] for a capability NO manifest provides, so the dependency is a sentence nothing
reads: the compiler resolves providers for enabled apps and hard strengths only, and a `wants` is
never looked up at all. Fix the NAME (it is usually a typo against the provider's own
capabilities[].name — `python3 platform/manager/reconcile.py validate` prints the full list), or
provide the capability, or, if something OUTSIDE this repo serves it, add it to PLATFORM_CAPABILITIES
in this gate with its reason.""", file=sys.stderr)
    if violations or undeclared or (args.strict and any(not r for *_, r in declared)):
        print("""
The capability graph is wrong about these apps: the compiler pulled the provider into the closure and
ordered bring-up around it, and the app then ran its own copy. Fix by pointing the app at the
provider, or - if it genuinely needs its own - by SAYING SO in the manifest:

    "use": [{ "capability": "sql", "own_instance": true, "reason": "why" }]

which keeps it visible in `bbox plan` and arguable in review.""", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
