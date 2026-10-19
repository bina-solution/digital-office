#!/usr/bin/env python3
"""declared-db-objects-lint — gate G69: every DB object a tracked .sql DECLARES exists after onboard.

    python3 scripts/refactor/declared-db-objects-lint.py [--self-test]

WHY THIS EXISTS. Measured 2026-08-24 on a live deployment:

    to_regclass('public.indox_dashboard_stats')  ->  ABSENT
    to_regclass('public.indox_sync_stats')       ->  ABSENT

scripts/ops/dashboard-stats-schema.sql declares both. Its header documented a `docker cp` + `psql
-f` procedure, and a repo-wide grep found the file referenced by that header and one BFF comment and
NOTHING ELSE - no hook, no bootstrap, no CI. So no fresh deployment ever received them, and the
INDOX dashboard 404d out of the box. The one machine where it worked had them applied by hand months
earlier, which is the worst possible state: the bug is invisible exactly where people look first.

IT WAS INVISIBLE FOR THE USUAL REASON. The BFF answers GET /dashboard/stats with HTTP 200 carrying
the 404 as its payload, so every health check and monitor read it as healthy. A gate that asks the
DATABASE what exists cannot be fooled that way - which is why this checks the object, not the
endpoint.

THIS IS A DIFFERENT QUESTION FROM THE OTHER SCHEMA GATES. G39/gen-indox-schema ask "does the code
agree with schema.sql". This asks "did anything ever RUN it". A file can be perfectly consistent
with every consumer and still be applied by nobody - that is precisely the defect here, and it is
the same shape as the schema.sql gap found earlier the same day.

SCOPE, deliberately narrow. Only files that are DECLARED OWNERS of live schema are read.
scripts/ops/migrations/*.sql is EXCLUDED on purpose: a migration is a historical one-shot describing
a transition, and an old migration's objects may have been legitimately dropped or renamed since.
Including them would produce exactly the kind of noisy roster people learn to ignore - the G67
lesson. Add a file here only when it is meant to describe the CURRENT shape of the database.

...AND ONLY WHERE THE APP RUNS. A file under apps/<id>/ or platform-base/<id>/ is that app's, and
its objects exist where that app's onboard hook has run - on an office that runs the app. Measured
2026-10-07 on hp-laptop, where indox is off: 30 objects "declared but ABSENT", every one of them
correctly absent. A schema an office does not run is not a finding (the same lesson G70 learnt
from seventeen hosts of apps nobody had installed), so the compiler is asked which apps are on
(`reconcile.py enabled-apps`) and the rest are named as not checked - a line of their own, never
the PASS line. When the compiler cannot say, everything is checked.
"""
import argparse
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

SOURCES = [
    # THE INDOX model. Already applied by the onboarding path; listed so that if that ever silently
    # stops happening, this gate says so instead of the deployment discovering it in production.
    "apps/indox/blueprint/fixtures/schema.sql",
    # The dashboard read model used to live in scripts/ops/dashboard-stats-schema.sql (applied by
    # nobody until 2026-08-24, superseded 2026-08-31 by the tenant schema above, file deleted
    # 2026-09-03 with the retired public.indox_sync_stats it also declared).
]

# `create table if not exists public.x`, `create or replace view x`, `create materialized view x`.
# to_regclass answers for all three, so they share a bucket.
RELATION = re.compile(
    r"create\s+(?:or\s+replace\s+)?(?:global\s+|local\s+)?(?:unlogged\s+|temporary\s+|temp\s+)?"
    r"(?:materialized\s+)?(?:table|view)\s+(?:if\s+not\s+exists\s+)?([\w.\"]+)", re.I)
FUNCTION = re.compile(r"create\s+(?:or\s+replace\s+)?function\s+([\w.\"]+)\s*\(", re.I)


def strip_sql_comments(text):
    """A CREATE inside a comment is documentation, not a declaration - counting it invents a
    finding that no file ever promised. The header of dashboard-stats-schema.sql is exactly such a
    comment block."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"--[^\n]*", " ", text)


def declared(text):
    """(relations, functions) as lowercase, schema-qualified names."""
    body = strip_sql_comments(text)
    def norm(n):
        n = n.replace('"', "").lower()
        return n if "." in n else "public." + n
    rels = {norm(m) for m in RELATION.findall(body)}
    fns = {norm(m) for m in FUNCTION.findall(body)}
    return rels, fns


def psql(container, sql):
    out = subprocess.run(
        ["docker", "exec", container, "psql", "-U", "postgres", "-d", "postgres", "-tAc", sql],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout or "psql failed").strip()[:300])
    return out.stdout.strip()


def app_of(rel):
    """The app a source belongs to (apps/<id>/..., platform-base/<id>/...); None for a platform file."""
    p = rel.split("/")
    return p[1] if p[0] in ("apps", "platform-base") and len(p) > 2 else None


def in_scope(sources, enabled):
    """(checked, skipped): a source is checked unless its app is one this office does not run.
    `enabled` is the set of app ids that are on, or None when nobody could say - then all of it."""
    checked = [r for r in sources if enabled is None or app_of(r) is None or app_of(r) in enabled]
    return checked, [r for r in sources if r not in checked]


def enabled_apps():
    """The ids of the apps this office runs - the compiler's own answer. None when it has none."""
    try:
        out = subprocess.run([sys.executable, "platform/manager/reconcile.py", "enabled-apps"],
                             cwd=REPO, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    ids = {ln.split()[1] for ln in out.stdout.splitlines() if len(ln.split()) == 2}
    return ids if out.returncode == 0 and ids else None


def deployment_name():
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("DEPLOYMENT_NAME="):
                return line.split("=", 1)[1].strip()
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--container", default=None)
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()

    sources, skipped = in_scope(SOURCES, enabled_apps())
    for rel in skipped:
        print("[declared-db-objects-lint] not checked here: %s - %s is not an app this office runs"
              % (rel, app_of(rel)))
    if not sources:
        print("[declared-db-objects-lint] NOT CHECKED - none of the %d source(s) belongs to an app "
              "this office runs. Nothing was asked of the database." % len(SOURCES))
        return 0
    rels, fns, per_file = set(), set(), {}
    for rel in sources:
        f = REPO / rel
        if not f.is_file():
            print("[declared-db-objects-lint] FAIL - declared source missing from the repo: %s" % rel)
            return 1
        r, n = declared(f.read_text(encoding="utf-8", errors="replace"))
        per_file[rel] = (r, n)
        rels |= r
        fns |= n

    if not rels and not fns:
        # An empty scan is a red, never a pass.
        print("[declared-db-objects-lint] FAIL - parsed ZERO objects from %d file(s). "
              "An empty scan is a red, never a pass." % len(sources))
        return 1

    container = a.container or ("supabase-db-%s" % deployment_name() if deployment_name() else None)
    if not container:
        print("[declared-db-objects-lint] FAIL - no DEPLOYMENT_NAME; cannot name the database "
              "container. This gate needs a running stack.")
        return 1

    try:
        missing_rel = [r for r in sorted(rels) if psql(container, "select to_regclass('%s');" % r) == ""]
        missing_fn = [n for n in sorted(fns) if psql(
            container,
            "select 1 from pg_proc p join pg_namespace ns on ns.oid=p.pronamespace "
            "where ns.nspname||'.'||p.proname = '%s' limit 1;" % n) == ""]
    except Exception as e:                                # noqa: BLE001
        print("[declared-db-objects-lint] FAIL - cannot query %s: %s" % (container, e))
        return 1

    print("[declared-db-objects-lint] %d relation(s) + %d function(s) declared across %d file(s)"
          % (len(rels), len(fns), len(sources)))
    if missing_rel or missing_fn:
        print("")
        print("[declared-db-objects-lint] FAIL - declared but ABSENT from the live database:")
        for r in missing_rel:
            owner = next((k for k, (rr, _) in per_file.items() if r in rr), "?")
            print("  relation  %-44s declared by %s" % (r, owner))
        for n in missing_fn:
            owner = next((k for k, (_, nn) in per_file.items() if n in nn), "?")
            print("  function  %-44s declared by %s" % (n, owner))
        print("")
        print("  A file that declares an object nothing applies is the defect - not the database.")
        print("  Fix the APPLY PATH (an onboarding hook), never by hand on one box: a hand-applied")
        print("  object makes the bug invisible exactly where people look first.")
        return 1

    print("[declared-db-objects-lint] PASS - every declared object exists")
    return 0


def self_test():
    """The parser is the risky half, so it is what gets tested - no database required."""
    cases = []

    r, f = declared("create table if not exists public.a (id int);")
    cases.append(("create table if not exists", (sorted(r), sorted(f)), (["public.a"], [])))

    r, f = declared("create or replace view b as select 1;")
    cases.append(("an unqualified name is assumed public", sorted(r), ["public.b"]))

    r, f = declared("create materialized view public.c as select 1;")
    cases.append(("materialized view", sorted(r), ["public.c"]))

    r, f = declared("create or replace function public.d() returns trigger as 'x' language plpgsql;")
    cases.append(("function", sorted(f), ["public.d"]))

    # The real trap: dashboard-stats-schema.sql's own header is a comment block describing how to
    # apply it, and an earlier draft of this parser counted CREATEs out of comments.
    r, f = declared("-- create table public.not_real (x int);\ncreate table public.real (x int);")
    cases.append(("a CREATE in a line comment is NOT a declaration", sorted(r), ["public.real"]))

    r, f = declared("/* create table public.blocked (x int); */ create table public.kept (x int);")
    cases.append(("a CREATE in a block comment is NOT a declaration", sorted(r), ["public.kept"]))

    r, f = declared('create table "Public"."Mixed" (x int);')
    cases.append(("quoted + mixed case is normalised", sorted(r), ["public.mixed"]))

    r, f = declared("create index idx_a on public.a (id);")
    cases.append(("an index is not a relation this gate tracks", (sorted(r), sorted(f)), ([], [])))

    a, b, p = "apps/indox/x/schema.sql", "apps/n8n/schema.sql", "scripts/ops/platform.sql"
    cases.append(("a source belongs to the app whose folder it is in", [app_of(a), app_of(b), app_of(p)],
                  ["indox", "n8n", None]))
    cases.append(("an app that is off: its schema is not checked, and is named",
                  in_scope([a, b, p], {"n8n"}), ([b, p], [a])))
    cases.append(("an app that is on: checked", in_scope([a], {"indox", "n8n"}), ([a], [])))
    cases.append(("a platform file is always checked", in_scope([p], set()), ([p], [])))
    cases.append(("nobody can say which apps are on: everything is checked",
                  in_scope([a, b, p], None), ([a, b, p], [])))

    bad = 0
    for name, got, want in cases:
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] %s (got %r, want %r)" % ("ok " if ok else "FAIL", name, got, want))

    # And it must actually find the real files' objects.
    for rel in SOURCES:
        f_ = REPO / rel
        if f_.is_file():
            r, n = declared(f_.read_text(encoding="utf-8", errors="replace"))
            ok = bool(r or n)
            bad += 0 if ok else 1
            print("  [%s] %s declares %d relation(s), %d function(s)"
                  % ("ok " if ok else "FAIL", rel, len(r), len(n)))

    print("")
    print("declared-db-objects-lint self-test: %s" % ("PASS" if not bad else "%d FAILED" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
