#!/usr/bin/env python3
"""The full timeline of an end-to-end run: every sync item and every document of a run, stage by
stage, with the time each stage took — from the sync ledger, the documents table and the action
execution log (nothing is inferred; a missing timestamp prints as a gap).

    python3 scripts/ops/indox-e2e-timeline.py --tenant hacohen --tag e2e-20260903T1500 [--json out.json]

`--tag` is the run marker the driver put into every subject / file name (indox-e2e-real.py);
rows are matched on the sync item's listing (subject or name) OR the document's NAME containing it.
Stages per item:  sent/uploaded → discovered → claimed → delivered (document created) → last action
→ COMPLETED (or the terminal status), with the action list and its n8n execution ids.

Runs on the docker host (laptop: WSL; server: root shell) — it talks to Postgres through the
supabase-db container only.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

DOCKER = os.environ.get("DOCKER_CMD", "docker -H unix:///run/bbox-docker.sock" if os.path.exists("/run/bbox-docker.sock") else "docker")


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def db_container() -> str:
    names = sh(f"{DOCKER} ps --format '{{{{.Names}}}}'").split()
    for n in names:
        if n.startswith("supabase-db"):
            return n
    raise SystemExit("no supabase-db container")


def psql_json(container: str, sql: str) -> list:
    """Run a SELECT that returns one json_agg column; empty → []."""
    out = subprocess.run(
        f"{DOCKER} exec -i {container} psql -U postgres -d postgres -Atq",
        shell=True, input=sql, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(out.stderr.strip())
    txt = out.stdout.strip()
    return json.loads(txt) if txt and txt != "null" else []


def ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def secs(a, b):
    if a is None or b is None:
        return None
    return round((b - a).total_seconds(), 1)


def fmt(x):
    return "—" if x is None else (f"{x:.0f}s" if x < 120 else f"{x/60:.1f}m")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--tag", required=True, help="the run marker in subjects / file names")
    ap.add_argument("--sent", help="JSON file the driver wrote: {platform_or_name: sent_at_iso}")
    ap.add_argument("--json", help="write the full timeline here")
    a = ap.parse_args()
    schema = f"indox_{a.tenant}"
    c = db_container()
    tag = a.tag.replace("'", "")

    items = psql_json(c, f"""
select coalesce(json_agg(row_to_json(t)), '[]'::json) from (
  select regexp_replace(l.source,'^[^/]*/','') as pipe, l.platform_id, l.status, l.attempts, l.last_error,
         l.discovered_at, l.claimed_at, l.delivered_at, l.doc_id,
         coalesce(l.listing->>'subject', l.listing->>'name') as title
    from {schema}.sync_ledger l
   where coalesce(l.listing->>'subject','') like '%{tag}%' or coalesce(l.listing->>'name','') like '%{tag}%'
   order by l.discovered_at) t;""")
    docs = psql_json(c, f"""
select coalesce(json_agg(row_to_json(t)), '[]'::json) from (
  select d."ID", d."NAME", d."STATUS", d."TYPE", d."SYNC_NAME", d."ERROR", d.created_at, d.updated_at,
         d."API_TOOLS_ID" is not null as ocr, d."AI_TYPE" is not null or d."AI_DOC_ID" is not null as ai,
         d."DOC_ID", d."DOC_DATE", d."DOC_TOTAL_AMOUNT", d."COMPANY_ID", d."SELECTION_CERTAINTY"
    from {schema}.incoming_documents d
   where d."NAME" like '%{tag}%' or d."ID" in (select doc_id from {schema}.sync_ledger where coalesce(listing->>'subject','') like '%{tag}%' or coalesce(listing->>'name','') like '%{tag}%')
   order by d.created_at) t;""")
    doc_ids = [d["ID"] for d in docs]
    actions = []
    if doc_ids:
        ids = ",".join(f"'{i}'" for i in doc_ids)
        actions = psql_json(c, f"""
select coalesce(json_agg(row_to_json(t)), '[]'::json) from (
  select "ID" as doc_id, "ACTION" as action, "EXECUTION_ID" as execution_id, "STARTED_AT" as started_at, "ENDED_AT" as ended_at
    from {schema}.indox_action_execution_log where "ID" in ({ids}) order by "STARTED_AT") t;""")

    sent = {}
    if a.sent and os.path.exists(a.sent):
        sent = json.load(open(a.sent, encoding="utf-8"))
    by_doc = {}
    for x in actions:
        by_doc.setdefault(x["doc_id"], []).append(x)
    docs_by_id = {d["ID"]: d for d in docs}

    rows = []
    print(f"run {a.tag} · tenant {a.tenant} · {len(items)} sync items · {len(docs)} documents · {len(actions)} actions\n")
    hdr = f"{'pipe':22} {'item':28} {'status':13} {'→disc':>7} {'→claim':>7} {'→deliv':>7} {'→done':>7} {'total':>7}  document → final status"
    print(hdr); print("-" * len(hdr))
    for it in items:
        key = it["title"] or it["platform_id"]
        sent_at = ts(sent.get(key) or sent.get(it["platform_id"]))
        disc, claim, deliv = ts(it["discovered_at"]), ts(it["claimed_at"]), ts(it["delivered_at"])
        d = docs_by_id.get(it["doc_id"]) if it.get("doc_id") else None
        acts = by_doc.get(it["doc_id"], []) if it.get("doc_id") else []
        done_at = None
        if d:
            last = ts(acts[-1]["ended_at"]) if acts and acts[-1].get("ended_at") else None
            done_at = last or ts(d["updated_at"])
        total = secs(sent_at or disc, done_at or deliv)
        rows.append({**it, "sent_at": sent_at.isoformat() if sent_at else None, "document": d,
                     "actions": [{"action": x["action"], "execution_id": x["execution_id"], "started_at": x["started_at"],
                                  "ended_at": x["ended_at"], "seconds": secs(ts(x["started_at"]), ts(x["ended_at"]))} for x in acts],
                     "stage_seconds": {"to_discovered": secs(sent_at, disc), "to_claimed": secs(disc, claim),
                                       "to_delivered": secs(claim, deliv), "to_done": secs(deliv, done_at), "total": total}})
        print(f"{it['pipe']:22} {str(key)[:28]:28} {it['status']:13} {fmt(secs(sent_at, disc)):>7} {fmt(secs(disc, claim)):>7} "
              f"{fmt(secs(claim, deliv)):>7} {fmt(secs(deliv, done_at)):>7} {fmt(total):>7}  "
              f"{(d['ID'] + ' → ' + str(d['STATUS']) + (' (' + str(d['ERROR'])[:60] + ')' if d.get('ERROR') else '')) if d else ('— ' + str(it['last_error'] or '')[:60])}")
        for x in acts:
            print(f"{'':22} {'':28} {'':13}   · {x['action']:32} {fmt(secs(ts(x['started_at']), ts(x['ended_at']))):>6}  exec {x['execution_id']}")
    # summary per pipe
    print("\nper pipe (median seconds): sent→discovered / discovered→delivered / delivered→done / total; items delivered / completed")
    import statistics
    for pipe in sorted({r["pipe"] for r in rows}):
        rs = [r for r in rows if r["pipe"] == pipe]
        def med(k):
            v = [r["stage_seconds"][k] for r in rs if r["stage_seconds"][k] is not None]
            return statistics.median(v) if v else None
        delivered = sum(1 for r in rs if r["status"] == "delivered")
        completed = sum(1 for r in rs if r.get("document") and r["document"]["STATUS"] == "COMPLETED")
        print(f"  {pipe:22} {fmt(med('to_discovered')):>7} {fmt(med('to_delivered')):>7} {fmt(med('to_done')):>7} {fmt(med('total')):>7}   {delivered}/{len(rs)} delivered, {completed}/{len(rs)} completed")
    if a.json:
        json.dump({"tag": a.tag, "tenant": a.tenant, "items": rows, "documents": docs}, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        print(f"\nwritten: {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
