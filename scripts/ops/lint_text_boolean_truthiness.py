#!/usr/bin/env python3
"""Find TEXT columns holding 'true'/'false' that workflow code reads as JS booleans.

THE BUG THIS FINDS
------------------
incoming_documents stores booleans as TEXT. In JavaScript the string 'false' is TRUTHY, so:

    if (!doc.X)                 never fires for a row whose X is the string 'false'
    if (doc.X)                  fires for BOTH 'true' and 'false'
    if (doc.X === true)         never fires at all -- a string is not a boolean
    if (doc.X !== true)         always fires

Every one of those runs cleanly, reports nothing, and takes the wrong branch forever.

Measured 2026-08-23: `!doc.PRIORITY_SYNC_COMPLETED` in the priority send gate meant 5,770 COMPLETED
documents -- every row explicitly marked the string 'false' -- read as ALREADY SYNCED and could
never be sent. Flipping activePrioritySync dispatched nothing at all, and looked like a dead
feature rather than a truthiness bug. Two sibling instances in the same file
(`=== true` / `!== true`) mean a skip documented as leaving ERP-synced documents alone has never
once fired.

The column list is derived FROM THE DATA -- any column whose non-null values are exactly
true/false -- so it cannot drift from a hand-maintained list.

SAFE FORMS (not reported): String(x).trim().toLowerCase() === 'true', a T()/truthy() helper,
x === 'true', x == 'true', JSON.parse(x). Those all read the text as text.

Exit 1 if any risky read is found.
"""
import glob
import io
import json
import os
import re
import subprocess
import sys

# three levels: scripts/ops/<file> -> scripts/ops -> scripts -> repo root.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
N8N_DIR = os.path.join(ROOT, "apps", "indox", "blueprint", "n8n")
DOCKER = ["wsl", "-d", "Ubuntu", "--", "docker", "-H", "unix:///run/bbox-docker.sock"]

COLUMN_SQL = """
-- ONE PASS, over a sample. The first version ran an EXISTS and a NOT EXISTS per column -- with
-- ~112 columns that is 224 full scans of a 39k-row table with to_jsonb per row, and it did not
-- finish. jsonb_each_text unpivots each row once instead, and a 5,000-row sample is ample for
-- deciding which columns hold booleans-as-text.
SELECT string_agg(key, ',')
FROM (
  SELECT kv.key,
         bool_and(kv.value IN ('true','false')) AS all_bool
  FROM (SELECT * FROM public.incoming_documents LIMIT 5000) d,
       LATERAL jsonb_each_text(to_jsonb(d)) kv
  WHERE kv.value IS NOT NULL AND kv.value <> ''
  GROUP BY kv.key
) z
WHERE all_bool;
"""


def text_boolean_columns():
    # Strip `--` comment lines BEFORE flattening to one line. Collapsing newlines first turns the
    # leading comment into a comment that swallows the whole query, and psql then returns nothing
    # at all -- which looks identical to "no boolean columns exist".
    sql = " ".join(l for l in COLUMN_SQL.split("\n") if not l.strip().startswith("--"))
    out = subprocess.run(
        DOCKER + ["exec", "-i", "supabase-db-shlomo-laptop", "psql", "-U", "postgres", "-tAc", sql],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0 or not out.stdout.strip():
        sys.stderr.write((out.stderr or "").strip()[:400] + "\n")
    return [c for c in out.stdout.strip().split(",") if c]


def scan(path, cols):
    text = io.open(path, encoding="utf-8").read()
    lines = text.split("\n")
    hits = []
    for col in cols:
        # risky: a bare truthiness read, or strict (in)equality against a JS boolean
        for pat, why in (
            (r"!\s*(?:doc|d|j|row|item\.json|\$json)\.%s\b" % col,
             "bare negation -- the string 'false' is truthy, so this never fires"),
            (r"(?<![=!])\b(?:doc|d|j|row)\.%s\s*===\s*(?:true|false)\b" % col,
             "strict equality against a JS boolean -- a string never matches"),
            (r"(?<![=!])\b(?:doc|d|j|row)\.%s\s*!==\s*(?:true|false)\b" % col,
             "strict inequality against a JS boolean -- always true"),
        ):
            for m in re.finditer(pat, text):
                n = text[:m.start()].count("\n") + 1
                src = lines[n - 1].strip()
                if src.startswith("//") or src.startswith("*"):
                    continue                      # a comment describing the bug is not the bug
                hits.append((n, col, why, src[:110]))
    return sorted(hits)


def main(argv):
    cols = text_boolean_columns()
    if not cols:
        print("  FATAL: could not derive the TEXT-boolean column list from the database")
        return 2
    print("  TEXT-boolean columns (derived from data): %d" % len(cols))
    print("    %s" % ", ".join(cols))
    targets = argv[1:] or sorted(glob.glob(os.path.join(N8N_DIR, "*.workflow.ts")))
    bad = 0
    for path in targets:
        for n, col, why, src in scan(path, cols):
            print("  %s:%d  %s" % (os.path.basename(path), n, col))
            print("      %s" % why)
            print("      %s" % src)
            bad += 1
    print("  %d risky read(s) across %d file(s)" % (bad, len(targets)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
