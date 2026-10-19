# INDOX SYNC — the complete outline (workflows · BFF · UI · data) + the UX rebuild

Everything below is read off the LIVE instance, not from memory.

---

# PART 1 — THE MACHINE: workflows and their numbered nodes

## 1.1 The live sync fleet

| workflow | name | nodes | role |
|---|---|---|---|
| `syncV3Main0001` | Sync v3 Reconcile | 28 | the 15-min conductor: lock → registry → units → run stamps |
| `syncV3Unit0001` | Sync v3 Source Unit | 26 | ONE pipe's pass: enumerate → DIFF → claim → deliver |
| `syncV3Deliver0001` | Sync v3 Deliver | 47 | one item's delivery + ledger + feedback (**~19 nodes dead — §1.3**) |
| `syncLedgerApi01` | Sync Ledger API | 37 | the kernel: DIFF / CLAIM / RECORD / RELEASE / ATTEMPT / GATE / CURSOR + 5-min reaper |
| `SyncProcGDoc0001` | Sync Processor - drive-gdoc | 25 | drive doc processor (download → classify → rename → move → upsert) |
| `SyncProcBS000001` | Sync Processor - drive-bs | 15 | drive balance-sheet processor (filename → company → move → upsert) |
| `indoxGmailDocDownloader01` | Gmail Documents Downloader | 35 | mail attachments → documents |
| `indoxGmailBSDownloader01` | Gmail Balance Sheet Downloader | 22 | BS mail → document (owns the 5-rule sender chain) |
| `indoxGmailLinkDownloader01` | Gmail Link Downloader 2.0 | 33 | intermediary mail → fetch document by link (7-way provider routing) |
| `SyncApi0000000001` | sync api | 26 | the `indox-manage` webhook: RESET / STATUS / SCAN / INJECT / RELEASE |
| `mailDiscovery01` | mail discovery (incremental) | 12 | UID-forward cursor walk over a Gmail label |
| `mailLabelEngine01` | Mail Label Engine | 41 | applies `tag_rules` → the labels that decide which pipe a mail belongs to |
| `SelectBase01` | base selection | 6 | company / type / date — **the one place base selection happens** |
| `SelectType01` | per-type selection + scoring | 5 | the per-type values + certainty |

## 1.2 Numbered nodes — the three that carry the sync

**`syncV3Main0001` (the conductor).** 1 Schedule 15m · 2 Manual Trigger · 3 When Called · 4 Try Lock ·
5 Lock Acquired? · 6 Skip: Already Running · 7 Registry Req · 8 Get Registry · 9 Build Units ·
10 Any Units? · 11 Units Loop · 12 **Run Unit** · 13 Renew Lock · 14 Collect Result · 15 Main Result ·
16 No Units · 17 Unlock (Done) · 18 Should Continue? · 19 Continue? · 20 Continue Pass ·
21 Run Start Req · 22 Stamp Run Start · 23 Run End Req · 24 Stamp Run End · 25 Main Reply.

**`syncV3Unit0001` (one pipe's pass).** 1 When Called · 2 Unit In · 3 Needs Settings? · 4 Prep Settings ·
5 **Load Settings** (the live `old_document_months_back`) · 6 Route Source · 7 List Req · 8 **List**
(drive, with `createdAfter`) · 9 Diff Req Drive · 10 Search Req · 11 **Search** (gmail, with
`newer_than`) · 12 Diff Req Gmail (**+`oldest_ms`**) · 13 **Call DIFF** · 14 Take X · 15 Has Work? ·
16 **Deliver Each** · 17 Gate Req · 18 Call GATE · 19 Unit Result · 20 Claim Req · 21 Call CLAIM ·
22 Claim Won · 23 Release Req · 24 Call RELEASE · 25 Loop Deliveries · 26 Pace Batch.

**`syncV3Deliver0001` (one item).** 1 When Called · 2 Item In · 3 **Route Mode** · 4 Route Kind ·
5 Route Proc Kind · 6 Drive Proc Payload · 7 **Run Drive Processor** · 8 Mail Proc Payload ·
9 **Run Mail Processor** · 10 Record Req P · 11-14 synced-label ops · **15-33 the inline
implementation (DEAD, §1.3)** · 26 Call RECORD · 34 Post Record Route · 35 Proj Kind · 36-37 Move ·
38-39 Label · 40 Result OK · 41-42 Attempt/backoff · 43-45 failed-label ops · 46 Result Fail.

## 1.3 The duplication you flagged in the screenshot — measured

`Route Mode` (node 3) splits `mode==='proc'` (delegate to a processor workflow) from an **inline
re-implementation** of drive/mail/link delivery (nodes 15-33). Every registry pipe declares a
`processor_wf`, so the switch always leaves on `proc`. **Sampled Deliver executions: 6/6 took
`proc`; `Split Attachments`, `Download Link` and all three `Call DELIVER*` fired zero times.**
~19 of 47 nodes are a second implementation nothing runs — including its own naive `Extract Link`
(a bare "first URL in the body" regex) beside the link downloader's 7-way provider engine.

---

# PART 2 — BFF: every sync route

`apps/indox/app/incoming_documents/api/__init__.py` — the sync surface is **≈3,790 of 9,283 lines
(41%)**, of which roughly **1,500 lines are prose**.

| method + path | reads | writes / triggers | UI caller |
|---|---|---|---|
| `GET /sync/registry` | registry + `indox_sync_stats` + `sync_pipe_state` + connections | — | the page poll |
| `GET /sync/inventory` | stats cache (live walk only on `?deep/with_done/sync`) | refreshes the cache row | the page poll · "מדוד" |
| **`GET /sync/flow`** *(new)* | `sync_ledger.delivered_at` in a window + stats | — | the new header strip |
| `GET /sync/items` | stats cache (heavy rows) | `?live=1` refreshes | the board columns |
| `GET /sync/runs` | `sync_pipe_state` | — | the flow strip (running only) |
| `GET /sync/engine` | engine manifest + ledger + last execution | — | מנוע tab |
| `GET /sync/reconcile` | ledger vs live source | — | בדיקת התאמה |
| `GET /sync/origin` | connection catalog | — | "מקור" link |
| `POST /sync/registry` · `PATCH/DELETE /sync/registry/<name>` | registry | `settings.sync_registry` (+ may create a Drive folder) | pipe editor |
| `POST /sync/registry/<name>/run` · `POST /sync/run` | registry | **`INLINE_ACTION: SCAN`** webhook | הרץ עכשיו / הרץ הכל |
| `POST /sync/items/move` | stats cache + drive snapshot | **source write** (drive move / gmail labels) + `RELEASE` + `sync_attempt` reset | board drag / drawer |
| `POST /sync/items/apply-fallback-type` | registry | doc `TYPE` write + move | board bulk |
| `GET /connections`, `GET/POST /connections/<id>/locations` | drive + mail services | creates a real label/folder | pipe editor |
| `GET /sync/status` | registry | — | **removed from the poll today (was dead)** |
| `POST /repos/<repo>/sync` | repo backend | kafka | **dead — no caller** |

**Dead query flags** (route supports them, nothing sends them): `?with_items=1` on `/sync/status`
and `/sync/registry`, `?deep=1` on `/sync/inventory`, `?live=1` on `/sync/items`.
**Vestigial mechanism:** `_inventory_entry` is called from exactly one place with
`deep=True, with_done=True` hardcoded — so the whole `counted`/`was_cached` machinery is a
constant, `_TTL_INVENTORY` never serves a hit on that path, and one branch of `_inventory_gmail`
is unreachable.

---

# PART 3 — UI: the component tree

```
/sync → SyncStatePage
├── header: title · instance · updated · [השהה רענון] · <FreshnessBadge/>   ← owns the only clock
├── <SyncFlow/>            ← NEW: window chips + files moved + real bar + live runs
├── callouts: refresh err · run skipped · reconcile · run err · stuck/broken conns
├── subnav: מקורות(N) · לוח פריטים(N) · מנוע
├── HUD "לפי רישום הסנכרון"        ← pipes view only now (labelled)
├── view=pipes  → HUD "לפי המקורות עצמם" (labelled) + PipeCard grid
│                 PipeCard = SourceWork · DoneWork · StateBar · LocationLine · chips · 4 actions
│                 overlays: ItemsDrawer · PipeEditor (4-step wizard)
├── view=board  → SyncBoard (4 virtualised columns, filters, drag, bulk bar)
└── view=engine → EngineView (pipeline diagram · ledger state · last run per pipe)
```

---

# PART 4 — DATA LAYER (live schemas + row counts)

| table | columns | rows |
|---|---|---|
| **`sync_ledger`** | `source · platform_id · status · doc_id · content_hash · delivered_at · claimed_at · instance` | **29,094** |
| **`sync_attempt`** | `source · platform_id · attempts · not_before · last_error · updated_at` | 577 |
| **`sync_cursor`** | `source · mode · walk_token · steady_cursor · updated_at` | 4 |
| **`sync_pipe_state`** | `source · instance · last_run · last_result · execution_id · workflow_id · run_status · run_started_at · run_finished_at · run_units_total/done/delivered/failed` | 2 |
| **`indox_sync_stats`** | `instance · sync_name · payload jsonb · **payload_light jsonb (generated)** · updated_at · error` | 18 |
| **`companies`** | `id · שם חברה · מזהה 1/2 · שם ספק מפריוריטי · **מייל 1/2** · הוראות AI · extra · TRUSTED_SOURCE_TYPES · instance` | 1,183 |
| **registry** | `settings.sync_registry` — ONE json row: name, source, connection, pairs/labels, batch, processor_wf, enabled, fallback_type | 8 pipes |

**`incoming_documents` — the sync/source contract columns:**
`ID · NAME · STATUS · TYPE · COMPANY_ID · LINK · LINK_CONNECTION · SOURCE_TYPE · SOURCE_ID ·
SOURCE_LINK · SOURCE_LIST(jsonb) · SYNC_NAME · CONNECTION · HASH · RECEIVED_DATE · DOC_DATE`
**+ today's additions:** `SENDER · SYNC_REGISTRY_ID · ATTACHMENT_TEXT · SEND_DATE ·
COMPANY_BY_SENDER · TYPE_BY_SOURCE`.

---

# PART 5 — WHAT WAS WRONG WITH THE UI, AND WHAT I CHANGED

## 5.1 The lag — root-caused and fixed

**The read model stored each pipe's ENTIRE item list in the same row as its counts.** Measured on
this instance: `payload` **24 MB** vs the counts in **18 kB** — a ~1,300× amplification, and
`/sync/registry` + `/sync/inventory` both paid it on **every 5-second poll**.

Fix: a **stored generated column** `payload_light = payload - 'items'` (no writer knows about it,
so it cannot drift) + a `light=True` read path for the three count endpoints. The items board
still reads the heavy row, scoped to the pipe and state it is showing.

| endpoint | before | after |
|---|---|---|
| `/sync/registry` | **3,957 ms** | **215 ms** |
| `/sync/inventory` | **3,956 ms** | **174 ms** |
| `/sync/status` | 147 ms | **removed from the poll** |
| whole poll | ~8 s every 5 s | **~0.4 s** |

Plus four React-level fixes: the **3-second clock moved out of the page into the badge** (it was
re-rendering the whole board, including three virtualised columns, twenty times a minute for one
boolean); `totals`/`stuckTotal`/`brokenConns` memoised; the dead `/sync/status` poll removed; and
the board **no longer remounts** on every drill-through (`key={boardSeed}` → an `initialCode` prop),
so scroll position, selection and all three loaded pages survive.

## 5.2 The two bars — replaced, not patched

They drew `run_units_done/total`, which the engine writes as `0/0` at Run Start and `units/units`
at Run End with **nothing in between** — so the bar could only ever be indeterminate or 100%. They
also rendered a permanent full green bar for every pipe that had *ever* run, and a canceled pass
appeared as "הסתיים · 100%".

**`<SyncFlow/>`** replaces them: the dashboard's window chips (הכל/15 דק׳/30 דק׳/שעה/היום/החודש,
persisted and shared with the dashboard) + **files that actually moved**, counted from
`sync_ledger.delivered_at` — with the estate's real source→INDOX position as the bar, and a live
run shown as a small chip with its n8n link only while it is genuinely running.
Verified live: switching 15 דק׳ → היום moved the count from **0** to **37 נמסרו**.

## 5.3 The screen is readable now

- **The ReadTimeout flood**: `/sync/items` returns every pipe's notes on every column, and each
  column rendered all of them — ~90 amber blocks pushing the cards below the fold. Now one
  collapsed line per column ("N מקורות לא נקראו במלואם"), details on click.
- **Failure chips actually drill through**: the chip passed its `code` and the handler discarded
  it, so clicking "החברה לא זוהתה · 156" opened an unfiltered board. Verified: clicking a chip now
  opens the board pre-filtered (903 items on the tested cause).
- **The two counter systems are labelled** — "לפי רישום הסנכרון (מה שהמנגנון תיעד)" vs
  "לפי המקורות עצמם (מה שיושב בתיקיות ובתוויות)". They legitimately differ; nothing said so.
- **The ledger HUD is hidden on the board**, where the columns already show those numbers and the
  tiles only cost vertical space.
- The bulk-action bar no longer sits under the floating drain pill.

---

# PART 6 — WHAT IS STILL ON THE LIST (UI)

1. `ItemsDrawer` duplicates the board's job in a non-virtualised overlay — fold it into the board.
2. `ago()` renders two different formats on one screen; `STATE_ORDER` and `ORDER` disagree on state
   order; `BigStat` exists in three copies.
3. `SyncBoard`'s ~60 CSS rules live in a `<style>` tag inside its render.
4. Four dead-UI systems behind `caps.claims` (the in_progress column, the תקועים chip/filter/tag)
   while `schema.sql` says the claim shipped — one of the two is stale.
5. `batch.schedule_min` is editable and honoured by nothing; `GLOBAL_SCHEDULE_MIN=15` is hand-synced
   to an n8n trigger.
6. The window is not yet pushed into `/sync/items` (the board still shows all-time); the strip is
   windowed, the board is not.
