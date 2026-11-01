#!/usr/bin/env python3
"""Acceptance scorecard for the 150-doc fresh-start goal.
Reports per-source COMPLETED/total, local-extraction accuracy (non-null + local-vs-AI agreement),
BS-line completion, system-at-rest, and errors. Reusable for every acceptance run.

  python scripts/acceptance-measure.py
"""
import subprocess

DB = ["docker", "exec", "supabase-db-shlomo-laptop", "psql", "-U", "postgres", "-d", "postgres", "-tAF,", "-c"]


def q(sql):
    out = subprocess.run(DB + [sql], capture_output=True, text=True, encoding="utf-8").stdout.strip()
    return [r.split(",") for r in out.splitlines() if r]


print("=" * 72)
print("ACCEPTANCE SCORECARD  (goal: 30/source COMPLETED, 100% extraction, BS lines, rest)")
print("=" * 72)

# per-source status
rows = q("""select coalesce("SOURCE_TYPE",'?'),
  count(*), count(*) filter(where "STATUS"='COMPLETED'),
  count(*) filter(where "STATUS"='IN_PROGRESS'),
  count(*) filter(where "STATUS" in ('NEEDS_REVIEW','ACTION_REQUIRED','MISSING_TYPE','MISSING_COMPANY_ID')),
  count(*) filter(where "ERROR" is not null and "ERROR"<>'')
  from incoming_documents where "ID"<>'__bootstrap__' group by 1 order by 1""")
print(f"\n{'SOURCE':<22}{'total':>7}{'done':>7}{'inprog':>8}{'review':>8}{'err':>6}")
for r in rows:
    print(f"{r[0]:<22}{r[1]:>7}{r[2]:>7}{r[3]:>8}{r[4]:>8}{r[5]:>6}")

# extraction accuracy on COMPLETED non-BS docs. Canonical values live in SELECTED_*; amount applies
# to INVOICE only (shipments legitimately have none). ERROR is a non-fatal log, NOT a failure flag.
base = "\"STATUS\"='COMPLETED' and \"SOURCE_TYPE\"<>'BALANCE_SHEET'"
inv = "\"STATUS\"='COMPLETED' and \"TYPE\"='INVOICE'"
acc = q(f"""select
  count(*) filter(where {base}),
  count(*) filter(where {base} and "TYPE" is not null),
  count(*) filter(where {base} and "COMPANY_ID" is not null),
  count(*) filter(where {base} and "DOC_DATE" is not null),
  count(*) filter(where {inv}),
  count(*) filter(where {inv} and "DOC_TOTAL_AMOUNT" is not null),
  count(*) filter(where "STATUS"='COMPLETED' and "AI_TYPE" is not null and "TYPE" is not null and lower("TYPE")=lower("AI_TYPE")),
  count(*) filter(where "STATUS"='COMPLETED' and "AI_TYPE" is not null),
  count(*) filter(where "STATUS"='COMPLETED' and "AI_COMPANY_ID" is not null and "COMPANY_ID" is not null and "COMPANY_ID"="AI_COMPANY_ID"),
  count(*) filter(where "STATUS"='COMPLETED' and "AI_COMPANY_ID" is not null)
  from incoming_documents where "ID"<>'__bootstrap__'""")[0]
n = int(acc[0]) or 1; ninv = int(acc[4]) or 1
print(f"\nLOCAL EXTRACTION ({acc[0]} COMPLETED non-BS docs; amount on {acc[4]} invoices):")
print(f"  TYPE {100*int(acc[1])//n}%   COMPANY {100*int(acc[2])//n}%   DATE {100*int(acc[3])//n}%   AMOUNT(inv) {100*int(acc[5])//ninv}%")
tm = int(acc[7]) or 1; cm = int(acc[9]) or 1
print(f"LOCAL vs AI agreement:  TYPE {100*int(acc[6])//tm}% (of {acc[7]} w/AI)   COMPANY {100*int(acc[8])//cm}% (of {acc[9]} w/AI)")
print("  (ERROR column is a non-fatal log, not a failure signal; failures = review/missing status)")

# BS lines
bs = q("""select count(*), count(*) filter(where "STATUS"='COMPLETED'),
  count(*) filter(where "BS_LINE_AMOUNT" is not null)
  from incoming_documents where "SOURCE_TYPE"='BALANCE_SHEET' and "ID"<>'__bootstrap__'""")[0]
print(f"\nBS LINES: total {bs[0]}  completed {bs[1]}  with-amount {bs[2]}")

# rest
rest = q("""select count(*) filter(where "STATUS"='IN_PROGRESS'),
  round(extract(epoch from (now()-max(updated_at)))) from incoming_documents where "ID"<>'__bootstrap__'""")[0]
print(f"\nREST: in_progress={rest[0]}  secs_since_last_update={rest[1]}  -> {'AT REST' if rest[0]=='0' else 'PROCESSING'}")
print("=" * 72)
