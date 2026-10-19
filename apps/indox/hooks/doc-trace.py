#!/usr/bin/env python3
"""INDOX per-document RUNTIME TRACER.

Aggregates the EXACT execution trace of one (or more) incoming_documents across ALL n8n
workflows/instances that touched it:

  doc_id  (doc_name)
    (timestamp | workflow | ACTION -> lastNode | status)
    (timestamp | workflow | ACTION -> lastNode | status)
    ...

Use this WHILE a test run is in flight to verify expected behaviour / stability / efficiency / speed,
instead of passively polling status counts. Spot: stale-lock 'Process Blocked Error', dead-end actions,
re-processing churn (same action repeating), slow per-action latency, and which node a doc dies on.

Usage:
  ./bbox app indox doc-trace <doc_id> [doc_id2 ...]
  ./bbox app indox doc-trace --status IN_PROGRESS [--limit 10]   # trace N docs in a status
  ./bbox app indox doc-trace --source BALANCE_SHEET --limit 5
"""
import sys, json, subprocess

DN = 'shlomo-laptop'
def sb(q):
    # direct exec args (no shell) -> column-name quotes are plain double-quotes
    r = subprocess.run(['docker','exec','supabase-db-'+DN,'psql','-U','postgres','-d','postgres','-t','-A','-F','|','-c',q.replace('\\"','"')],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return [l for l in r.stdout.splitlines() if l.strip()]
def n8(q):
    r = subprocess.run(['docker','exec','n8n-postgres-'+DN,'sh','-c',
                        f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -F"|" -c "{q}"'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return [l for l in r.stdout.splitlines() if l.strip()]

def deref(arr, v, depth=0):
    while isinstance(v, str) and v.isdigit() and int(v) < len(arr) and depth < 4:
        nv = arr[int(v)]
        if nv == v: break
        v = nv; depth += 1
    return v

def trace_doc(doc_id):
    rows = sb(f"select coalesce(\\\"NAME\\\",'-'), coalesce(\\\"STATUS\\\",'-'), coalesce(\\\"TYPE\\\",'-'), coalesce(\\\"SOURCE_TYPE\\\",'-') from incoming_documents where \\\"ID\\\"='{doc_id}'")
    meta = rows[0].split('|') if rows else ['?','?','?','?']
    print(f"\n=== {doc_id}  ({meta[0]})  [{meta[2]}/{meta[3]} -> {meta[1]}] ===")
    # MAIN-workflow executions for this doc, oldest first. We focus on main (sv5xx) because the
    # data layer ('INDOX API','Get Incoming Document','Batch Upsert') does GetAll calls whose payload
    # contains EVERY doc id (spurious cross-matches). Main's ACTION is doc-specific = the real timeline.
    # Pass MAIN_ONLY=0 env to include all workflows (noisy).
    import os
    only = os.environ.get('MAIN_ONLY','1') == '1'
    wf_filter = "and w.id='sv5xxRBVGxvV0kXx' " if only else ""
    ex = n8(f"select e.id, w.name, e.status, to_char(e.\\\"startedAt\\\",'HH24:MI:SS') from execution_entity e join workflow_entity w on w.id=e.\\\"workflowId\\\" join execution_data d on d.\\\"executionId\\\"=e.id where d.data like '%{doc_id}%' {wf_filter}order by e.\\\"startedAt\\\" asc")
    if not ex:
        print("  (no executions referenced this doc)"); return
    for line in ex:
        p = line.split('|')
        if len(p) < 4: continue
        eid, wf, st, ts = p[0], p[1], p[2], p[3]
        # decode ACTION + lastNodeExecuted for main; for others just lastNode
        dd = n8(f"select data from execution_data where \\\"executionId\\\"={eid}")
        action = lastnode = '?'
        if dd:
            raw = '|'.join(dd)
            try:
                arr = json.loads(raw)
                import re
                m = re.search(r'\"ACTION\":\"(\d+)\"', raw)
                if m: action = deref(arr, m.group(1))
                m = re.search(r'\"lastNodeExecuted\":\"(\d+)\"', raw)
                if m: lastnode = deref(arr, m.group(1))
            except Exception:
                pass
        act = f"{action} -> " if action not in ('?', None) else ""
        print(f"  ({ts} | {wf[:28]:28} | {act}{lastnode} | {st})")

def main():
    a = sys.argv[1:]
    ids = []
    if a and a[0] == '--status':
        status = a[1]; limit = 10
        if '--limit' in a: limit = int(a[a.index('--limit')+1])
        ids = [r for r in sb(f"select \\\"ID\\\" from incoming_documents where \\\"STATUS\\\"='{status}' and \\\"ID\\\"<>'__bootstrap__' order by updated_at asc limit {limit}")]
    elif a and a[0] == '--source':
        src = a[1]; limit = 10
        if '--limit' in a: limit = int(a[a.index('--limit')+1])
        ids = [r for r in sb(f"select \\\"ID\\\" from incoming_documents where \\\"SOURCE_TYPE\\\"='{src}' and \\\"ID\\\"<>'__bootstrap__' order by updated_at asc limit {limit}")]
    else:
        ids = a
    if not ids:
        print("usage: indox-doc-trace.py <doc_id ...> | --status STATUS [--limit N] | --source SRC [--limit N]"); return
    for d in ids: trace_doc(d.strip())

if __name__ == '__main__':
    main()
