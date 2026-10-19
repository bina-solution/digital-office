#!/usr/bin/env python3
"""layering-lint — gate G9: a base app may never name a layer-3 app.

    python3 scripts/refactor/layering-lint.py [--strict]

The layer split is only real if it constrains dependencies. `platform-base/` is the base every
deployment needs; `apps/` is what a user chooses to install. So the arrow may only point one way:

    apps/ (layer 3)  ------uses----->  platform-base/ (layers 1-2)
    platform-base/   --NEVER names-->  apps/

A base app that hardcodes a layer-3 name is broken by definition: uninstall that app and the base
still refers to it. `platform-base/glitchtip/blueprint.yml` listing `my-docs`, `drive`,
`mailview`, `apitools` is the canonical example — remove one of those apps and glitchtip still
provisions an error-reporting project for a service that does not exist.

The fix is never "delete the reference". It is to INVERT it: the layer-3 app declares what it
wants in its own `app.json`, and the compiler emits that into the base app's config. The app
stays self-contained and the base app stops knowing its consumers by name.

Categories are reported separately because they invert differently:

  config     base-app compose/registries naming a layer-3 service   -> declare in app.json
  rollout    a layer-3 app's override file stored under a base app  -> move into the app
  workflow   an app-specific n8n workflow parked in platform-base   -> move to apps/<id>/blueprint

--strict fails on any non-zero total (the end state). Without it the counts print as a
scoreboard, which is what you want mid-migration.
"""
import argparse, json, pathlib, re, sys

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required")

REPO = pathlib.Path(__file__).resolve().parents[2]
BASE, APPS = REPO / "platform-base", REPO / "apps"

# Names that are exempt because they are the app's OWN identity inside its own tree, or are
# generic English that collides with an app id (localmail's routing host is "email").
# "/fixtures/" USED to be here, and that hole is how layer 2 came to declare a layer-3 app's entire
# data model. apps/n8n/fixtures/01_schema.sql — first line: "-- INDOX schema" — defined ten
# INDOX tables plus drive's file index, and this gate never saw it because the path was skipped. The
# exemption is now scoped to fixtures that live INSIDE an app's own tree, where naming the app is
# self-reference rather than inversion.
SKIP_DIRS = ("/node_modules/", "/static/", "/examples/", "/qa/", "/docs/", "/_archive/",
             "/workflows-archive/", "/_v2_precentralize_bak/", "/synth-demo-docs/")
#: fixtures are exempt only under apps/<id>/ — an app may name itself in its own files.
APP_OWNED_FIXTURES = "/fixtures/"
SKIP_FILES = {"readme.md", "release.md", "changelog.md", "truth.json",
              # compiled output written INTO a base app's mounted dir — it names
              # layer-3 apps precisely BECAUSE the inversion worked.
              "zz-generated-apps.yaml"}


def layer3_tokens():
    """Layer-3 app ids + the container names their compose defines. Short/generic names are
    dropped: matching them in prose produces noise, not findings."""
    toks = {}
    for m in sorted(APPS.glob("*/app.json")):
        d = json.loads(m.read_text(encoding="utf-8"))
        names = {d["id"]}
        comp = d.get("compose")
        if comp and (m.parent / comp).exists():
            doc = yaml.safe_load((m.parent / comp).read_text(encoding="utf-8")) or {}
            names |= set((doc.get("services") or {}).keys())
        for n in names:
            if len(n) > 4:
                toks[n] = d["id"]
    # historical spellings of the indox container
    toks.setdefault("incoming-documents", "indox")
    toks.setdefault("incoming-docs", "indox")
    return toks


# Keys whose VALUES wire one service to another. A layer-3 name here is real coupling.
WIRING_KEYS = {"url", "image", "source", "service", "services", "consumers", "container",
               # `name` IS a reference in a projects/providers list — excluding it made
               # G9 blind to the exact glitchtip bug it was written for (self-test).
               "name",
               "volumes", "environment", "env", "depends_on", "host", "external_host",
               "compose", "build", "context", "probe", "target", "slug", "embed"}
# Keys that hold human prose or a captured snapshot. A layer-3 name here is a WORD, not a wire:
#   now/title/desc/note  — English describing what a secret is for
#   active_workflows     — a snapshot n8n-pull captures FROM the live instance, not an authored
#                          list; it names indox workflows because those workflows are running
# Counting these was inflating the debt with things no uninstall could ever break.
# Workflow JSON: what makes a node actually TALK to another app.
WF_WIRING_KEYS = {"url", "workflowId", "value", "key", "topic", "path", "host", "endpoint",
                  "jsCode", "functionCode", "query", "command"}
# ...and what is only labelling. `name` is a node/workflow label here (unlike a projects list,
# where it IS the reference), and `tags` categorise — neither is a dependency.
WF_PROSE_KEYS = {"name", "tags", "description", "notes", "displayName", "subtitle", "color"}

PROSE_KEYS = {"now", "title", "desc", "description", "note", "notes", "summary", "why",
              # an `id:` is the thing's OWN name, never a reference to another app — the
              # connections catalog has a secret literally called `localmail`
              "id",
              "active_workflows", "workflows", "tags", "labels", "comment", "hint", "next"}


def _is_external_url_path(val, m):
    """True when the match is a PATH SEGMENT of a third-party URL, not our service's host.

    Renaming localdrive -> `drive` collided with Google's own API:
    https://www.googleapis.com/drive/v3/files. That is Google Drive, not our container. A
    reference to OUR service always addresses it as a host — http://drive:8975 or drive:8975 —
    so only count the token when it sits in the host position.
    """
    start = m.start()
    # find the URL this match sits inside, if any
    for proto in ("http://", "https://"):
        i = val.rfind(proto, 0, start)
        if i == -1:
            continue
        host_start = i + len(proto)
        host_end = min([x for x in (val.find(c, host_start) for c in "/?#") if x != -1]
                       + [len(val)])
        if start >= host_end:
            return True          # matched after the host -> a path segment
        return False             # matched inside the host -> ours
    return False


def _is_vendor_namespace(key, val, m):
    """True when the match is the PUBLISHER half of an image reference, not one of our services.

    Same class of collision as `_is_external_url_path` above, one field over. `platform-base/postgres`
    runs `image: supabase/postgres:15.8.1.085` — the postgres build the Supabase COMPANY publishes on
    Docker Hub, kept because the live data volume was initdb'd by it (vanilla postgres:17 is a
    separate migration with a data step). `supabase/` there is a Docker Hub namespace that happens to
    spell the same word as `apps/supabase`.

    It also fails this gate's own definition of the bug: "uninstall that app and the base still
    refers to it". Disable the supabase gallery app and `docker pull supabase/postgres` still works —
    Docker Hub has no opinion about which of our apps are enabled. Nothing can break, so there is
    nothing to invert; the base has no way to own a database image via the app that sits on top of it.

    Deliberately narrow: ONLY the namespace is exempt. An image whose REPOSITORY name is a layer-3
    app — `ghcr.io/bina/apitools:v1` inside a base compose, i.e. a base app building an installable
    one — still counts, which is the case `image` was put in WIRING_KEYS for.
    """
    if key != "image":
        return False
    name = val.split("@", 1)[0]          # drop any digest; tag stays with the repo half
    slash = name.rfind("/")              # last "/" ends [registry/]namespace, starts the repository
    return slash != -1 and m.end() <= slash


def _walk(node, key=None):
    """Yield (key, scalar) for every leaf, remembering the key it hangs off."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, str(k))
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, key)
    elif node is not None:
        yield key, str(node)


# A layer-3 app dialled by container DNS from base-layer SOURCE — http://drive:8975,
# https://mailapi:8970. The scheme+port is what makes it wiring rather than a word in a sentence.
CODE_ENDPOINT = re.compile(r"https?://([A-Za-z0-9][\w-]*):\d+")
# A layer-3 app id used to INDEX something in base code — APP_BASES['mailview'],
# source_health["apitools"]. The compiled registry exists precisely so base code never has to name
# an app; subscripting it by a literal id defeats that and raises KeyError once the app is removed.
# Deliberately narrower than "any quoted app id in base source": that also matched
# `icon: "inbox"` in the console's JS, a Feather icon name with nothing to do with the app.
CODE_SUBSCRIPT = re.compile(r"""\w\s*\[\s*["']([a-z0-9][\w-]*)["']\s*\]""")


def scan():
    toks = layer3_tokens()
    pat = re.compile(r"(?<![\w-])(" + "|".join(sorted(map(re.escape, toks), key=len, reverse=True)) + r")(?![\w-])")
    config, rollout, workflow = [], [], []

    for f in sorted(BASE.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(REPO).as_posix()
        if f.name.lower() in SKIP_FILES:
            continue
        is_wf = "/n8n/workflows/" in "/" + rel
        if any(s in "/" + rel for s in SKIP_DIRS):
            continue
        # A fixture may name the app that owns it — but only from inside that app's tree. The same
        # path under platform-base is layer 2 shipping a layer-3 app's data, which is what this gate
        # exists to find.
        if APP_OWNED_FIXTURES in "/" + rel and rel.startswith("apps/"):
            continue
        # Extensionless-but-executable counts: every app hook in platform-base/*/hooks/ is a
        # shebang script with no suffix, and a suffix-only test skipped all of them. Caught by
        # this gate's own self-test, which planted an inversion in a hook and saw nothing.
        is_code = f.suffix in (".py", ".js", ".ts", ".sh") or (
            f.suffix == "" and f.open("rb").read(2) == b"#!")
        if not is_code and f.suffix not in (".yml", ".yaml", ".json", ".env")                 and f.name != "docker-compose.yml":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # What layer 0 RENDERED into a base app's directory is not that app's source. The edge's
        # `zz-serve.yaml` is written by the compiler from this office's `remote:` block (gitignored,
        # stamped on its first line) and names every app a linked office gives — which is the
        # compiler doing its job, and was counted here as the edge naming four apps.
        if text.startswith("# GENERATED"):
            continue

        # Base-layer SOURCE counts too. Scanning only config was a blind spot that hid a textbook
        # inversion for the whole refactor: platform-base/console/app.py carried
        # SVC_BASES = {"drive": "http://drive:8975", "mail": "http://mailapi:8970"} — a layer-2 file
        # naming two layer-3 apps, which you had to edit to add a third. In code the wiring has no
        # key to hang off, so the signal is the shape that actually breaks on uninstall: dialling a
        # layer-3 app by its container DNS name. Prose and comments never match that.
        if is_code:
            # Strip comments first. A comment cannot break when the app is uninstalled, and the
            # comment DOCUMENTING this very fix quotes the endpoints it removed — so a gate that
            # reads comments reports the fix as the bug.
            code = re.sub(r"(?m)(^|\s)(#|//).*$", " ", text)
            owners = {toks[m.group(1)]
                      for rx in (CODE_ENDPOINT, CODE_SUBSCRIPT)
                      for m in rx.finditer(code) if m.group(1) in toks}
            if owners:
                config.append((rel, sorted(owners)))
            continue

        owners = set()
        try:
            doc = (json.loads(text) if f.suffix == ".json"
                   else yaml.safe_load(re.sub(r"!\w+", "", text)))
        except Exception:
            doc = None

        if doc is not None and not is_wf:
            # A service NAME is a mapping key, and _walk only ever yields leaf VALUES with the key
            # they hang off — so a base compose could declare a whole service called after a layer-3
            # app and this gate reported PASS. It did: apps/n8n/docker-compose.yml defined
            # `indox-demo-docs`, a container serving one app's demo fixtures, from layer 2.
            #
            # Only `services:` keys, deliberately. Every other mapping key in a compose file is a
            # field name, and treating those as references would flag the schema, not the wiring.
            #
            # NOT matched with `pat`: that pattern excludes hyphen-adjacent hits (?<![\w-])/(?![\w-])
            # so compound words do not produce prose noise — which is exactly what hid
            # `indox-demo-docs`. In a service NAME the hyphen is the opposite signal: `<app>-anything`
            # is a container the base declares on an app's behalf, the strongest inversion there is.
            if isinstance(doc, dict) and isinstance(doc.get("services"), dict):
                for svc in doc["services"]:
                    s = str(svc)
                    for tok, owner in toks.items():
                        if s == tok or s.startswith(tok + "-"):
                            owners.add(owner)
                            break

            # Structural pass: only values hanging off a wiring key count.
            for k, val in _walk(doc):
                if k in PROSE_KEYS or (k not in WIRING_KEYS and k is not None):
                    continue
                for m in pat.finditer(val):
                    if _is_vendor_namespace(k, val, m):
                        continue
                    owners.add(toks[m.group(1)])
                    break
        elif doc is not None:
            # Workflows: structural too, but with a workflow-shaped notion of "wiring". A node
            # that CALLS http://apitools:8080, or executes another app's sub-workflow, is
            # app-specific. A tag named "indox", a tool description mentioning incoming
            # documents, or a node label are categorisation and prose — they cannot break when
            # the app is uninstalled, and counting them made shared stdlib look app-owned.
            for k, val in _walk(doc):
                if k in WF_PROSE_KEYS or k not in WF_WIRING_KEYS:
                    continue
                for m in pat.finditer(val):
                    if _is_external_url_path(val, m):
                        continue
                    owners.add(toks[m.group(1)])
        else:
            for line in text.splitlines():
                if line.strip().startswith("#"):
                    continue
                m = pat.search(line)
                if m:
                    owners.add(toks[m.group(1)])

        if not owners:
            continue
        if is_wf:
            workflow.append((rel, sorted(owners)))
        elif "/rollout/" in "/" + rel:
            rollout.append((rel, sorted(owners)))
        else:
            config.append((rel, sorted(owners)))
    return config, rollout, workflow


#: directories under platform-base/*/ that hold data rather than mechanism, and are therefore
#: candidates for being some app's corpus rather than the platform's own.
#: `docs` is a base app's own documentation: an app that CITES it (a comment pointing at
#: `<base app>/docs/<page>.md`) is the arrow pointing the right way, not a payload the platform
#: stores for somebody else.
_ORPHAN_SKIP = {"_archive", "hooks", "lib", "extensions", "schema", "credentials", "workflows",
                "static", "templates", "node_modules", "__pycache__", "docs"}


def scan_orphan_data():
    """Base directories that ONLY layer-3 code reads.

    The naming rules above catch a base file that says "indox". They do not catch a base DIRECTORY
    whose name is generic but whose contents belong to one app — which is how
    apps/n8n/demo-docs (INDOX's invoices, balance sheets and companies.json) and
    synth-demo-docs and demo/ sat in layer 2 unflagged for as long as they did. Ownership is not in
    the name there, it is in who reads it.

    So ask that instead: for each data directory under a base app, who references it? If every
    referrer lives under apps/, the platform is storing a payload it never opens, and the directory
    belongs with the app that does.

    Deliberately quiet about directories nobody references at all — that is dead weight, a different
    complaint, and reporting it here would bury the real inversions.
    """
    import subprocess as sp
    rows = []
    for base_app in sorted(p for p in BASE.iterdir() if p.is_dir()):
        for d in sorted(p for p in base_app.iterdir() if p.is_dir()):
            if d.name in _ORPHAN_SKIP or d.name.startswith("."):
                continue
            needle = f"{base_app.name}/{d.name}"
            try:
                out = sp.run(["git", "grep", "-l", "-F", needle], cwd=REPO,
                             capture_output=True, text=True, timeout=120).stdout
            except Exception:
                continue
            refs = [r for r in out.splitlines() if r and not r.startswith("legacy/")
                    and "/_archive/" not in r and not r.startswith("ai/context/")
                    and not r.startswith(".refactor/") and not r.startswith("issues/")]
            app_refs = {r.split("/")[1] for r in refs if r.startswith("apps/")}
            base_refs = [r for r in refs if not r.startswith("apps/")
                         and "layering-lint" not in r]
            if app_refs and not base_refs:
                rows.append((d.relative_to(REPO).as_posix(), sorted(app_refs)))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    config, rollout, workflow = scan()
    cats = [
        ("base config naming a layer-3 app", config, "declare it in the app's app.json; compile it in"),
        ("layer-3 override files under a base app", rollout, "move the file into apps/<id>/"),
        ("app-specific workflows in platform-base", workflow, "move to apps/<id>/blueprint/n8n/"),
        ("base data read only by layer-3 apps", scan_orphan_data(),
         "move to apps/<id>/blueprint/; mount it back via app.json contributes.volumes"),
    ]
    print(f"{'LAYER-INVERSION DEBT':46} {'files':>6}")
    print("-" * 54)
    total = 0
    for label, rows, fix in cats:
        print(f"{label:46} {len(rows):>6}")
        total += len(rows)
        if rows and (a.verbose or len(rows) <= 12):
            for rel, owners in rows:
                print(f"    {rel}  [{', '.join(owners)}]")
        elif rows:
            for rel, owners in rows[:8]:
                print(f"    {rel}  [{', '.join(owners)}]")
            print(f"    … +{len(rows) - 8} more (-v for all)")
        if rows:
            print(f"    -> {fix}")
    print("-" * 54)
    print(f"{'TOTAL':46} {total:>6}")

    if total == 0:
        print("\nG9 PASS — no base app names a layer-3 app. The dependency arrow points one way.")
        return 0
    if a.strict:
        print("\nG9 FAIL (--strict) — the layering invariant is not yet met.")
        return 1
    print("\nG9 progress — run with --strict once the debt reaches zero to lock the invariant in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
