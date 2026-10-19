# INDOX runtime attention — trace every test doc, don't just poll status

## Principle (operator directive 2026-06-22)
When a test run is in flight, **do NOT passively wait on status counts**. Actively review the n8n RUNTIME and
build the EXACT execution trace of **each** document you uploaded, aggregated per doc across ALL workflows/
instances that touched it:

```
doc_id  (doc_name)
  (timestamp | workflow | action / node | status)
  (timestamp | workflow | action / node | status)
  ...                                   # every instance/execution regarding that doc, in order
```

Use the trace to verify, continuously: expected behaviour, stability, efficiency, and speed — per document,
not in aggregate.

## Tool
`python3 scripts/indox-doc-trace.py <doc_id ...>`
`python3 scripts/indox-doc-trace.py --status IN_PROGRESS --limit 10`
`python3 scripts/indox-doc-trace.py --source BALANCE_SHEET --limit 5`

It finds every `execution_entity` whose `execution_data` references the doc id, and prints
`(HH:MM:SS | workflow | ACTION -> lastNodeExecuted | status)` oldest-first. (ACTION/lastNode are resolved
from n8n's flattened execution_data ref-array.)

## What to look for in a trace
- **Process Blocked Error** as lastNode → the per-doc Redis lock (`n8n.process_lock.doc_step.<id>`) is held
  (stale, often from a restart that interrupted an action between lock and Batch-Upsert-unlock). The doc is
  frozen until the lock clears. Fix: clear stale locks for non-actively-running docs.
- **Same ACTION repeating across many timestamps** → re-processing churn / a step that doesn't persist its
  write-back (doc never advances). Check the Batch-Upsert write for that field.
- **Long gaps between a doc's executions** → it's waiting in the poll backlog (poll limit/interval too small
  for the doc count), NOT being worked. Speed = backlog drain time; watch it doesn't exceed the terminalizer
  window (else false NEEDS_REVIEW — see [[indox-supabase-unlock-and-storm]]).
- **lastNode = a no-action / dead-end node** (e.g. Map NO ACTION, MISSING_LINK) → Determine Action routed the
  doc to a terminal-without-completion path; inspect the gate.
- **status=error + which node** → the failing node (DNS/API/expression). Cross-ref the memory on
  [[stack-memory-pressure-flakiness]] (memory-pressure DNS) and [[indox-supabase-text-boolean-bug]].

## ⚠️ Restart leaves STALE LOCKS (frequent gotcha)
Every n8n restart interrupts in-flight main executions BETWEEN lock-acquire and Batch-Upsert-unlock,
leaving stale `n8n.process_lock.doc_step.<id>` keys (TTL 2h — too long to self-recover). Symptom: docs
freeze IN_PROGRESS, tracer shows `lastNode=Process Blocked Error`, COMPLETED count stalls. After ANY
restart during active processing, clear stale locks so the backlog resumes:
```
RP=$(grep -E '^REDIS_PASSWORD=' .env|head -1|cut -d= -f2-|tr -d '\r"')
for k in $(docker exec redis-shlomo-laptop redis-cli -a "$RP" --no-auth-warning --scan --pattern 'n8n.process_lock.doc_step.*'|tr -d '\r'); do docker exec redis-shlomo-laptop redis-cli -a "$RP" --no-auth-warning del "$k" >/dev/null; done
docker exec supabase-db-shlomo-laptop psql -U postgres -d postgres -c "update incoming_documents set updated_at=now() where \"STATUS\"='IN_PROGRESS' and \"ID\"<>'__bootstrap__';"
```
Verified 2026-06-22: 40 stale locks froze 45 docs at Process Blocked Error; clearing → COMPLETED resumed
34→51. (Better long-term: shorter lock TTL or a SessionStart hook that clears doc_step locks on boot.)

## Per-doc expected happy-path (supabase)
- **BS doc**: ingest → extract_balance_sheet → (verify) → link_documents (OPENS one INVOICE row per BS line,
  SOURCE_TYPE=BALANCE_SHEET) → mark_completed.
- **BS-line invoice** (child, SOURCE_TYPE=BALANCE_SHEET): get_short_doc_id → update_name → check_from_office →
  find_link (best-effort) → select_invoice_values → action_priority_sync → mark_completed (completes as a line
  record; no own file required — see gdocAction isBsLine exemption).
- **gdoc invoice (real file)**: get_short_doc_id → find_link → get_api_tools_id → query_* → extract_invoice_google_ai
  → select → priority_sync → mark_completed.
- Lock protocol: main locks doc_step → action → Batch-Upsert writes + UNLOCKS → line-change → next action.
