# Deep audit findings (2026-08-05) — the defects we had NOT already found

Produced by a read-only sweep hunting for more instances of the three failure patterns established
earlier in the day. Everything below was verified against live state unless marked otherwise.
**None of these are fixed yet** except where noted.

The dominant pattern, again: **a bounded query treated as the whole truth.** That is now the single
most common defect class in this codebase — 4 instances found this morning, 8 more below.

---

## HIGH — silent data loss / wrong results

### H1. The poller silently drops every row past 1000, permanently
`apps/indox/app/incoming_documents/poller.py:45` → `backends/supabase.py:172-175`
`fetch_all()` calls `transport.select()` with **no limit**, so PostgREST applies its own 1000-row
cap. `sync_repo_once()` then treats that page as the complete current state: it diffs it for
`ROW_CREATED`/`ROW_CHANGED` events **and overwrites the on-disk snapshot with it**. The live table
holds 6,211 rows. Every row past the first page is dropped from tracking on every poll — no change
event ever fires, and it's gone from the snapshot. The file's own `_paged_select` docstring
documents the cap that this call path ignores.

### H2. Document counts shown in the UI are capped at 1000
`api/__init__.py:2895-2910` (`_get_cached_row_count`) — computes the repo document count as
`len(repo_obj.fetch_all())`, hitting the same cap, **even though an exact-count primitive already
exists** (`SupabaseRepo.count()` with `Prefer: count=exact`) and is used correctly one function
away. Every row count in the stats panel and instance switcher is silently wrong above 1000.

### H3. Sync-board and reconcile counts truncate at 300 messages
`api/__init__.py:1652-1677`, `1826-1847`, `1976-1999` — `_gmail_messages()` returns one page
(≤`INDOX_SYNC_MAIL_LIMIT`, default 300) and both `_entry_items` (board counts) and
`_reconcile_entry` (divergence diff) consume it as the whole label. `gmail-doc` alone has **922**.
The sibling `_inventory_gmail` in the same file *does* detect this and emits `partial_note`; these
two callers don't. Real reconciliation divergences past row 300 are invisible.

### H4. Settings cache serves stale config for up to 20 minutes
`indoxSettings01.json` nodes `KVStorage1/3/5` (`"ttl": 1200`) vs the BFF's settings PATCH handler.
The BFF writes `activePrioritySync`, `indox_execution_mode`, `max_actions_per_doc` straight to the
DB; n8n keeps serving the cached values with **no invalidation hook**. Every document-processing
workflow can run 20 minutes on stale settings after an operator saves. Silent.

### H5. The mailbox delete-guard protects an account that doesn't exist
`apps/mail/docker-compose.yml:45,477` + `mailapi/local_app.py:73` default `LOCALMAIL_USER` to
`"indox"`; `docker-compose.yml:366` + `mailboxd/mailboxd.py:79` default it to `"admin"`. If the var
is unset (explicitly supported), the real mailbox is `indox@…` while the delete-protection guards
`admin@…` — so **the account the app depends on is freely deletable through the UI**.
`mailapi/profiles.py:76-78` documents the team hitting this exact bug once already for `MAIL_DOMAIN`.

### H6. A ghost workflow has been failing to activate 12,196+ times
n8n keeps retrying activation of workflow id `indoxSetupWF001` ("Incoming Documents — Setup"),
failing every time with *"has no node to start the workflow"*. Verified: that id exists in
`workflow_entity`, `webhook_entity`, `workflow_history` — **nowhere** — and nowhere in the repo. A
stale reference from a previous rename that nothing cleared. Infinite retry with backoff, forever.

### H7. A busy live workflow calls a workflow that does not exist
`indoxV2Driver01.json` node **"Snooze Incoming Document"** targets `bdchh5urW9lBzudZ`, which has
**zero rows** in `workflow_entity` and zero executions ever — its only definition is in
`platform-base/n8n/_archive/`. The node is currently `disabled: true`, so it is inert today, but
`indoxV2Driver01` shows **57 production errors** with runtimes ~21× its successful runs (10.5s vs
495ms). Correlation, not proof — worth confirming during the error triage.

### H8. Three workflows are flagged active but can never run
`whatsappSendDoc01`, `indoxV2BSTest01`, `indoxV2DocBaseTest01` — each contains only a
`manualTrigger`, no schedule/webhook/poller, yet carries `active=true`. n8n retries activation
forever (~155 log lines each). This is the answer to "active but zero executions": these three plus
the ghost in H6.

---

## MEDIUM

| # | Finding | Where |
|---|---|---|
| M1 | Missing backslash: `replace(/D/g,'')` strips the letter **D**, not non-digits — breaks the trusted-supplier key so `TRUSTED_SUPPLIER` auto-approval silently never fires for any ח.פ. written with dashes/dots | `indoxSettings01.json` node `Companies` — ✅ **FIXED + pushed live, verified in n8n's DB** |
| M2 | `normalizeCompanyID` truncates a 9-digit ח.פ. to its **last 6 digits**, then gates a 100%-certainty `TRUSTED_SUPPLIER` auto-approval on equality. Two companies sharing a 6-digit suffix → the wrong company auto-approved on a financial document. Also masks genuine AI-vs-keyword mismatches | `indoxV2ActionsShip01`, `indoxV2ActionsGDoc01`, `indoxV2Driver01` |
| M3 | `_ledger_rows` — single unpaginated `limit=5000` for a pipe's whole ledger, feeding the divergence diff | `api/__init__.py:1938-1948` |
| M4 | `/sync/reconcile` status snapshot: `limit=20000` with tenant filtering applied in Python **after** the fetch | `api/__init__.py:3787-3796` |
| M5 | Company/tag-rule counts as `len(select(limit=2000))` instead of an exact count | `api/__init__.py:2960-2990`, `3161-3166` |
| M6 | `GET /config/tag_rules` docstring says "All rows", uses unpaginated `limit=2000` — its sibling `/config/companies` correctly uses `_paged_select` | `api/__init__.py:4319-4331` |
| M7 | Fallout from the known `folders()` 600-cap: with >600 folders `_ensure_folder` can miss an existing folder and **create a duplicate** | `api/__init__.py:1186-1228` |
| M8 | n8n containers restarted **31+ times**; each restart bulk-marks in-flight executions `crashed` — 247 of 328 crashes in 24h are `indoxApiSupabase01` purely because it's the shared gateway with the most in-flight work. Memory ruled out (~15% of 2GB, no OOM). The restart frequency itself is the issue | operational |
| M9 | `"dbTime.getTime is not a function"` — **12,196 occurrences** in ~36h. Executions still succeed, but it buries genuine errors in logs and GlitchTip | n8n main |
| M10 | `INCOMING_DOCS_API_PREFIX` is env-configurable server-side but **hardcoded** in the compiled SPA — they match today, but nothing forces it | `docker-compose.yml:42` vs `api.ts:26` |

---

## LOW

- **L1** Two independently tracked copies of the tag-rules seed fixture (`apps/indox/blueprint/fixtures/tag_rules.json`, `apps/mail/mailapi/fixtures/tag_rules.json`) — byte-identical today, no shared generation step.
- **L2** The known `slice(-5)` truncation is used as a **matching key** in 5 more places (`indoxGmailLinkDownloader01:467`, `indoxV2Driver01:3235,4108`, `indoxV2ActionsShip01:3131,3168`, `indoxV2ActionsBS01:1197,1239`) — the collision risk spans the whole shipment/BS matching pipeline.
- **L3** `JQExV3Order00001.json` has no discoverable caller — its four siblings each have a `JQExV3Run*` webhook wrapper; the Order one was never built.
- **L4** `indoxGmailActionsScanner01` is self-scheduled and outside the `sync_registry` dispatch its sibling downloaders use — possible legacy path running in parallel with sync-v3.
- **L5** GSheet-backend credential env vars have no reachable configured repo (`repos.json` is supabase-only).
- **L6** `owner_id` holds an **email address** in the Google drive adapter but a real `profile_id` in the local adapter — same field name, different kinds. Display-only today.

---

## Verified clean (recorded so nobody re-checks)

- **Schema drift: none.** Live `public.incoming_documents` columns match `schema.sql` exactly, including the new `THUMBNAIL`/`THUMBNAIL_COMPLETED`/`CONNECTION` columns and the `instance` tenancy column.
- **`PG Get All` CAP=20000** — live row count 6,211, ~3.2× headroom.
- **`sync_ledger` namespacing** — all rows correctly `incoming-documents-main/<pipe>`.
- **Mail `before_uid` cursor pagination** — correctly implemented; the bug is only that `_gmail_messages` never uses it.
- **`repos.json` / `active_instance.json`** — no stale pointers.
- Message/thread identity in both mail backends derives from real server-native ids — no truncation.

---

## A note on the audit channel

The auditing agent reported receiving messages it read as an injection attempt — framed as from a
"coordinator", telling it to stay held and to accept unverified claims as fact. Two of those were
legitimately mine (a task brief and a reply affirming its refusal to fabricate, which did mention
two fixes I had genuinely made and verified). Whether the others were real injection or crossed
wires, the agent's response was correct: it refused to state an unverified conclusion, kept the
sweep read-only, and flagged it. Recorded because the finding quality above depended on exactly
that discipline.
