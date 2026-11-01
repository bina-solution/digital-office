# INDOX sync — the whole solution, in one place (2026-08-25)

What sync is responsible for, and what it deliberately is not: **sync sharpens the source.** It
decides which items exist at a source, claims them exactly once, hands each one to a processor,
and records what happened. It does **not** decide a document's company or type — it supplies the
evidence (`SENDER`, `SYNC_REGISTRY_ID`, `ATTACHMENT_TEXT`, `SEND_DATE`, `RECEIVED_DATE`) and the
selection stage adjudicates. Every fact below was read off the live stack, not inferred.

---

## 1. The engine — five workflows, in the order a file moves through them

```
        (schedule 15m)                     (per pipe)                  (per item)
syncV3Main0001  ──────────────►  syncV3Unit0001  ──────────────►  syncV3Deliver0001
 "Sync v3 Reconcile"              "Sync v3 Source Unit"            "Sync v3 Deliver"
  28 nodes / 27 edges              26 nodes / 29 edges              47 nodes / 72 edges
        │                                  │                               │
        │  reads the registry              │  enumerate + DIFF + claim     │  proc | thin
        │  takes the recon mutex           │  (ledger says what is new)    │
        ▼                                  ▼                               ▼
   processLock01                     syncLedgerApi01                  a processor
                                    "Sync Ledger API"                 (see §2)
                                     37 nodes / 35 edges
```

| workflow | id | nodes/edges | what it owns |
|---|---|---|---|
| Sync v3 Reconcile | `syncV3Main0001` | 28 / 27 | the 15-minute pass. Reads `sync_registry`, holds the recon mutex via `processLock01`, builds one work unit per **enabled** pipe, stamps `sync_pipe_state`, writes the `indox_sync_stats` read model. |
| Sync v3 Source Unit | `syncV3Unit0001` | 26 / 29 | one pipe. Enumerates the source (drive folder / gmail label), DIFFs against `sync_ledger`, claims what is new, applies the `monthsOld` bound, dispatches per item. |
| Sync v3 Deliver | `syncV3Deliver0001` | 47 / 72 | one item. `Route Mode` picks the lane (§2), runs it, then records the ledger row and applies source feedback (labels/folder moves). |
| Sync Ledger API | `syncLedgerApi01` | 37 / 35 | every read/write of `sync_ledger` / `sync_attempt` / `sync_cursor`, including the retry due-union and the age bound. |
| sync api | `SyncApi0000000001` | 22 / 18 | the `/webhook/indox-manage` control plane. Verbs: **SCAN · INJECT · RELEASE** (RESET and STATUS retired 2026-08-25). |

Supporting, shared with the rest of the platform: `processLock01` (mutexes), `gmailApiImap01`
and `mailDiscovery01` (mail transport), `driveApi01` (drive transport), `indoxApi01` (the ONE
document writer — every row INDOX creates goes through its UPSERT/DELIVER paths).

### `syncV3Deliver0001` — the two lanes

`Item In` computes `mode = j.mode || (j.processor_wf ? 'proc' : 'thin')`, then:

* **`proc` (output 0)** — `Route Proc Kind` → `Run Drive Processor` / `Run Mail Processor`.
  The processor does the fetching, uploading and figuring, and returns a result. This is what
  the six processor-backed pipes use.
* **`thin` (output 1)** — `Route Kind` → the inline lane (`Drive Row` / `Gmail Row` / `Link Row`
  and their `Call Deliver *` / `Record Req *` tails). Sync writes the row and the ordinary INDOX
  state machine does the figuring. **This lane is live**, used by `drive-whatsapp-bot`
  (`"v3_mode": "thin"`), and proven to reach COMPLETED with correct company and type.

Both lanes converge on `Record Req P` → `Call RECORD` (one ledger record per *ledger item*, i.e.
per message or file) and then `Post Record Route` → label/move feedback.

## 2. Processors — where a source's own complexity lives

| pipe | processor | notes |
|---|---|---|
| `drive-gdoc-scanned`, `drive-gdoc-chat-export` | `SyncProcGDoc0001` (25 / 30) | drive files; writes the source contract + `LINK_CONNECTION`; STATUS requires company AND a real type, else IN_PROGRESS. |
| `drive-bs` | `SyncProcBS000001` (15 / 17) | balance-sheet drive files. |
| `gmail-doc` | `indoxGmailDocDownloader01` (35 / 35) | carries several documents inside ONE item via `doc_links`. |
| `gmail-bs` | `indoxGmailBSDownloader01` (22 / 20) | fans out **one item per surviving attachment** (`Find Balance Doc`), garbage-filtered. |
| `gmail-link` | `indoxGmailLinkDownloader01` (33 / 34) | resolves a LINK to bytes: provider branches by sender domain (morning / invoice-maven / senzey / invoice-one / ezcount / a known-standard list), then drive-share links, then a generic HTML resolver. |
| `drive-whatsapp-bot`, `mail-private` | *(none)* | `thin` lane by configuration. `mail-private` is `enabled:false`, provenance-only. |

## 3. Control plane — `SyncApi0000000001`, webhook `POST /webhook/indox-manage`

```
Webhook ─┐                                    ┌─ out0 INJECT  → Inject Dispatch
         ├─► Normalize ─► Action (switch) ────┼─ out1 SCAN    → Scan Registry → Scan Guard
When Called ┘                                 │                 → Runnable? → Call Scan → Scan Result
                                              ├─ out2 RELEASE → Release Registry Req → Get Release
                                              │                 Registry → Release Req →
                                              │                 Runnable Release? → Call Release
                                              └─ out3 fallback → Unknown Action
```

`Normalize` defaults a missing verb to `STATUS`, which now lands on the fallback and refuses with
`unknown INLINE_ACTION 'STATUS' (SCAN | INJECT | RELEASE)` — deliberate, so an old caller gets a
clear answer instead of silence.

## 4. BFF — every sync route (`apps/indox/app/incoming_documents/api/__init__.py`)

| method | route | what it answers |
|---|---|---|
| GET | `/sync/registry` | the registry, enriched per pipe (counts, connection health, last run). `with_items=False` by default — computing the estate on every mutation reply is what made this slow. |
| POST | `/sync/registry` | create a pipe (same validation the fixture converge path uses). |
| PATCH | `/sync/registry/<name>` | edit a pipe. |
| DELETE | `/sync/registry/<name>` | remove a pipe — **refused** if `sync_ledger` holds rows for it. |
| POST | `/sync/registry/<name>/run` | SCAN one pipe (proxies the manage webhook). |
| POST | `/sync/run` | SCAN everything. |
| GET | `/sync/status` | reachability + optional live counts. Answered from platform-services, never the webhook. |
| GET | `/sync/inventory` | per pipe: `at_source` / `in_indox` / `remaining`. `in_indox: null` means NOT COMPUTED (fast mode, or a mail listing bounded at 300) and must render as "—", never 0. |
| GET | `/sync/flow` | the time-windowed strip: delivered / in_flight / waiting / failed / at_source / in_indox / remaining. |
| GET | `/sync/items` | the item board (3 columns). |
| POST | `/sync/items/move` | CLAIM/ADVANCE — writes the SOURCE (drive folder / gmail label); the table follows. Illegal transitions are refused per item, never for the whole request. |
| POST | `/sync/items/apply-fallback-type` | stamp a pipe's fallback type onto chosen items. |
| GET | `/sync/runs` | run history; a pass running >45 min reports `stale`. |
| GET | `/sync/engine` | engine per pipe (v1/v3). |
| GET | `/sync/origin`, `/sync/reconcile` | provenance + reconcile views. |

Read-model caching: `_TTL_SYNC_STATS = 75s`, primed by the stats loop; `payload_light` is a
stored generated column (`payload - 'items'`) so the common reads never touch the 24 MB item
arrays — that single change took the registry read from 3,957 ms to 215 ms.

## 5. UI — three files, 2,747 lines

| file | lines | role |
|---|---|---|
| `pages/SyncStatePage.tsx` | 1,648 | the page: window chips (הכל / 15m / 30m / hour / today / month), the flow strip, the registry totals, the source cards, the tab switch (מקורות / לוח פריטים / מנוע). Owns polling; `FreshnessBadge` owns its own clock so a 3-second tick re-renders one span instead of the whole board. |
| `pages/SyncBoard.tsx` | 968 | the item board — three virtualised columns, bulk selection, per-item actions. |
| `components/SyncFlow.tsx` | 131 | the flow strip: delivered / in-motion / remaining plus the real `in_indox`-over-`at_source` progress bar, and running-only run chips. |

Component tree:

```
SyncStatePage
├── FreshnessBadge            (own timer; "חי" vs "לא מעודכן — <ago>")
├── window chips              → drives /sync/flow
├── SyncFlow                  → delivered · in motion · remaining + progress bar
├── registry totals strip     (לסנכרון / בתהליך / סונכרן / נכשל / מקורות / תקועים)
├── source cards  × N
│   ├── SourceWork            at_source · in_indox · remaining + bar   ← "—" when not computed
│   ├── StateBar              4-state bar, every segment a button
│   ├── failure-reason list   (grouped, Hebrew)
│   └── actions               הרץ עכשיו · עריכה · השהה/הפעל · מחיקה
└── SyncBoard                 (tab) — to_sync / in_progress / synced / failed
```

## 6. Data layer

```sql
sync_ledger      (source, platform_id, status, doc_id, content_hash,
                  delivered_at, claimed_at, instance)
sync_attempt     (source, platform_id, attempts, not_before, last_error, updated_at)
sync_cursor      (source, mode, walk_token, steady_cursor, updated_at)
sync_pipe_state  (source, last_run, last_result, updated_at, instance, execution_id,
                  workflow_id, run_status, run_started_at, run_finished_at,
                  run_units_total, run_units_done, run_delivered, run_failed)
indox_sync_stats (instance, sync_name, payload jsonb, updated_at, error,
                  payload_light jsonb)          -- payload_light = payload - 'items'
```

`source` is namespaced `<instance>/<pipe>` since phase 6b; the registry names pipes plainly, so
every join must normalise with `regexp_replace(source,'^[^/]*/','')`. Joining raw matches nothing
and silently reports zero delivered for every pipe.

The columns sync owns on `incoming_documents`: `SOURCE_ID` (**the** join key back to
`sync_ledger.platform_id` — not `LINK_CONNECTION`), `SOURCE_TYPE`, `SOURCE_LINK`, `SOURCE_LIST`,
`HASH`, `LINK`, `LINK_CONNECTION`, `NAME`, `SYNC_NAME`, `SYNC_REGISTRY_ID`, `SENDER`,
`ATTACHMENT_TEXT`, `RECEIVED_DATE`, `SEND_DATE`.

## 7. The rules that are easy to get wrong

1. **`enabled`, not `active`.** The registry field is `enabled`. A script keying on `active`
   defaults every entry to true and reports disabled pipes as live.
2. **`SOURCE_ID` is the join key.** `LINK_CONNECTION` is a connection id, not a file handle.
3. **Unknown is not zero.** `in_indox: null` means not computed.
4. **One source handle is not always one artifact.** A drive file id is; a mail message id is
   not — its attachments are siblings. Identity = same bytes (HASH), or same handle **and same
   name**.
5. **`monthsOld` is enforced at three enumeration points** — gmail `newer_than`, drive
   `createdAfter`, and the retry due-union's age bound — and again at the OLD gate on documents.
6. **The thin lane is not legacy.** No `processor_wf` means `thin` by design.
7. **`indoxDrainOn` is never needed for a manual drain**, and turning it on stacks a second wave.
