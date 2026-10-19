#!/usr/bin/env python3
"""Build a database from the fixture schema and diff its columns against the live one.

WHY THIS EXISTS SEPARATELY FROM lint_schema_drift.py
----------------------------------------------------
That gate compares CREATE statements -- does every object a migration creates also appear in
`schema.sql`. It is object-level, and it is not enough.

Measured 2026-08-23: `public.sync_ledger` was missing `claimed_at` and `instance` in the fixture
schema while the live table had both, and syncLedgerApi01's CLAIM op runs

    insert into public.sync_ledger (source,platform_id,status,claimed_at,delivered_at)

so a freshly provisioned database fails that insert outright. The object-level gate could not see
it -- the TABLE exists in both, only its columns differ. It was found by accident while
syntax-checking an unrelated edit, and accident is not a control.

WHY IT APPLIES THE SCHEMA INSTEAD OF PARSING IT
-----------------------------------------------
The first version of this file regex-parsed `create table (...)` out of schema.sql. It compared
ONE table and reported `coalesce(jsonb_agg(...` as a missing column -- the regex ran past the
table body into function definitions. SQL is not a regular language and a 1,400-line schema full
of plpgsql bodies will defeat any pattern short of a parser.

So it does the real thing: creates a scratch database, applies `schema.sql` to it, reads
`information_schema` from BOTH, drops the scratch. That is exact by construction, and it is also
the question that actually matters -- not "what does the file appear to say" but "what do you get
when you run it", which is what `bbox run` does on a new machine.

Both directions are reported; only one fails:
  MISSING FROM FRESH   live has it, a fresh database would not  -> BREAKS new deployments
  MISSING FROM LIVE    fresh has it, this database does not     -> an unapplied migration, local

usage: lint_schema_columns_vs_live.py [--keep]
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def _wslpath(*parts):
    return "/mnt/c" + os.path.join(ROOT, *parts).replace("C:", "").replace("\\", "/")


# APPLY ORDER, taken from schema.sql's own header comment:
#   platform-base 01_platform.sql (defines touch_updated_at) -> this -> 99_grants.sql
# Applying schema.sql alone fails at the first trigger calling touch_updated_at. The first version
# of this check did exactly that and nearly reported a broken bootstrap -- the instruction was on
# line 13 of the very file being tested.
APPLY_ORDER = [
    _wslpath("apps", "n8n", "schema", "01_platform.sql"),
    _wslpath("apps", "indox", "blueprint", "fixtures", "schema.sql"),
]
CTR = "supabase-db-shlomo-laptop"
SCRATCH = "indox_schema_freshcheck"
DK = "docker -H unix:///run/bbox-docker.sock"


def wsl(cmd):
    return subprocess.run(["wsl", "-d", "Ubuntu", "--", "bash", "-lc", cmd],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def psql(db, sql):
    return wsl("%s exec -i %s psql -U postgres -d %s -tAc \"%s\"" % (DK, CTR, db, sql))


def columns(db):
    r = psql(db, "SELECT table_name||'.'||lower(column_name) FROM information_schema.columns "
                 "WHERE table_schema='public' ORDER BY 1")
    return {l.strip() for l in (r.stdout or "").split("\n") if l.strip()}


def main(argv):
    keep = "--keep" in argv
    wsl("%s exec -i %s psql -U postgres -tAc \"DROP DATABASE IF EXISTS %s\"" % (DK, CTR, SCRATCH))
    r = wsl("%s exec -i %s psql -U postgres -tAc \"CREATE DATABASE %s\"" % (DK, CTR, SCRATCH))
    if r.returncode != 0:
        print("  FATAL: could not create the scratch database\n  %s" % (r.stderr or "").strip()[:300])
        return 2
    try:
        for src in APPLY_ORDER:
            ap = wsl("%s exec -i %s psql -U postgres -d %s -v ON_ERROR_STOP=1 -f - < '%s'"
                     % (DK, CTR, SCRATCH, src))
            if ap.returncode != 0:
                print("  FATAL: %s does not apply to a fresh database -- that is itself the bug"
                      % src.rsplit("/", 1)[-1])
                for line in (ap.stderr or "").strip().split("\n")[:8]:
                    print("    %s" % line[:160])
                return 1
            print("  applied %s" % src.rsplit("/", 1)[-1])
        fresh = columns(SCRATCH)
        live = columns("postgres")
        if not fresh or not live:
            print("  FATAL: could not read information_schema (fresh=%d live=%d)"
                  % (len(fresh), len(live)))
            return 2
        shared = {c.split(".")[0] for c in fresh} & {c.split(".")[0] for c in live}
        missing_fresh = sorted(c for c in live - fresh if c.split(".")[0] in shared)
        missing_live = sorted(c for c in fresh - live if c.split(".")[0] in shared)
        print("  fresh database: %d columns   live: %d   tables in both: %d"
              % (len(fresh), len(live), len(shared)))
        for c in missing_fresh:
            print("  BREAKS NEW DEPLOYS  %s   (live has it, a fresh database would not)" % c)
        for c in missing_live:
            print("  live is behind      %s   (fresh has it, this database does not)" % c)
        if missing_fresh:
            print("  FAIL: %d column(s) exist live and would be absent from a fresh deployment."
                  % len(missing_fresh))
            return 1
        print("  ok: every column this database has, a fresh one built from schema.sql also has")
        return 0
    finally:
        if not keep:
            wsl("%s exec -i %s psql -U postgres -tAc \"DROP DATABASE IF EXISTS %s\""
                % (DK, CTR, SCRATCH))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
