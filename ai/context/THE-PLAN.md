# THE PLAN — everything, in one place

**2026-08-05.** Supersedes every earlier plan doc. One source of truth: what was asked, what is done,
what is left, who is blocked on whom, and what only the owner can do.

Companion documents: [`INDOX-UNIFIED-N8N-SPEC.md`](INDOX-UNIFIED-N8N-SPEC.md) (target architecture) ·
[`OWNER-MESSAGES-FULL.md`](OWNER-MESSAGES-FULL.md) (all 249 directives) ·
[`COVERAGE-RECONCILIATION-2026-08-05.md`](COVERAGE-RECONCILIATION-2026-08-05.md) ·
[`INDOX-CODEBASE-MAP-2026-08-05.md`](INDOX-CODEBASE-MAP-2026-08-05.md) ·
[`LIVE-QA-2026-08-05-RERUN.md`](LIVE-QA-2026-08-05-RERUN.md)

---

## The goal, in one paragraph

A perfect, stable INDOX app, proven live for hacohen, with **100% of incoming documents** from mail
and drive reaching `COMPLETED`. Sustained **5,000+ documents/month**, 180,000 over three years.
Unified logic, preferably in n8n, one pattern for data and API, ERP-grade UI that stays fast at scale.

---

## Where we actually are

**The number that reframed everything:** the 6,207 rows in `incoming_documents` are **not** six months
of client documents. `created_at` spans 6 days, 97.4% bulk-inserted today; `SYNC_NAME` is set on 29
rows (0.47%); the ledger shows **~90 real lifetime deliveries**. True organic coverage is **under
0.3%**, not the 30% reported earlier.

**And the target is bigger than estimated.** A fully paginated mail scan found 8,490 messages in the
6-month window, 6,083 with attachments, at 2.035 attachments each → **~12,348 mail documents**.
Drive contributes 19,683 in-window files. Overlap measured at **~0** (the Gmail→Drive destination
folders were empty — proof that pipe never ran). **De-duplicated 6-month total: ~32,000 documents**,
i.e. ~5,300/month, not 3,000.

So this is **not a backfill of a mostly-working system. It is a first real run.**

---

## Part 1 — Done and verified

Each proven against the running system.

**Data reach.** Drive `_list()` followed no `nextPageToken` — it was hiding **43,326 of 78,651** client
files. `shared_folders()` (200) and `folders()` (600) uncapped. Mail `hasAttachment` was structurally
always-false; fixed, along with the latent `_dec()` crash that fix exposed.

**Mail.** Label engine searched **INBOX only** — 0 results where `[Gmail]/All Mail` returns 115. Fixed;
the owner's ERCO invoice now carries `DOC_TO_SYNC`. Per-message triage indicator shipped.

**Mail deposits.** All four mail registries lacked `drive_profile_id`/`drive_connection_id`, so every
upload fell through to the service account, which by design refuses. Fixed at the data layer; real
client documents now land in `automations/gmail-doc` (`מ.ש. הכהנים חומרי בנין`, `איטונג-22028`).
`drive api` errors **8/15min → 0**.

**Throughput.** `syncV3Unit0001`'s "Deliver Each" ran in n8n's `mode:"each"` — a sequential `await`
loop using one worker slot while 16 sat idle. Proof: **61% of deliveries were CANCELED** (259/424).
Fixed async; `syncV3Unit0001` p95 **829s → 5.6–38s**, 15 deliveries firing in a 9-second window.
Reconcile **981s → 299s**, now inside its 900s schedule.

**Backend.** Six HIGH defects fixed with live before/after: poller reported `row_count: 1000` against
6,207 real; the 300-message reconcile window judging 38,643 messages; `folders()` capped; the
20-minute settings cache; and the `LOCALMAIL_USER` guard **protecting a mailbox that does not exist**
while the real one was unguarded.

**Endpoints**, cold: `/sync/status` >90s → **0.05s** · `/sync/inventory` >90s → **3.7s** ·
`/sync/items` 46.7s → **4.1s** · `/sync/registry` 43.9s → **0.17s**.

**Table (QA-verified at rerun).** Pagination works · inline STATUS → `ACTION_RESTART` round-trips and
the engine acts on it · month badges exact (March 2026: **1,507**, was 236) · all **8 registries**
render · **1,503 rows** of raw 502 HTML purged · sort, search, card-view degradation confirmed.

**Document page.** Both broken tabs fixed — it was calling extraction-*testing* routes whose ids can
never match a real `doc_<hash>`.

**Hygiene.** 30 gates + 11 self-tests. `errorWorkflow` dangling refs **21 → 1**. Root cause fixed:
`hooks/push:507` defaulted to a dead id and re-stamped it on every push. Stuck-claim reaper live on a
5-minute schedule. `seed.sh` made insert-only; 18 live-operational keys removed from the demo fixture.
Gateway + identity workflows deployed.

---

## Part 2 — The three defect patterns

Forty-plus defects, three causes.

**A · A bounded query treated as the whole truth (~18).** Worst form invisible at the call site:
`PGRST_DB_MAX_ROWS=1000` silently caps every unpaged select regardless of the requested limit.
`_ledger_rows` asked 5,000, `sync_engine` asked 20,000 — both got 1,000, forever, with no error.

**B · The false clean (most dangerous).** `sync_engine` capped *before* filtering by instance →
`reachable:true` with empty counts. `executeWorkflowTrigger` silently drops undeclared fields →
`NEXT_RETRY_AT` set on **0 of 6,207** rows, so retry scheduling has never once worked. Eight switches
discarding documents with no error. `flow-qa.py --url` has no login code, so it reported 0 characters
of content instead of failing. `seed.sh` overwrote the live registry and printed `ok`.

**C · Two sources of truth.** Blueprint vs n8n DB · demo fixture vs live settings · declared trigger
schema vs actual table · `tag_rules` in Supabase vs the mail app's JSON. All drift silently.

**The structural root:** **65 of 66 workflows write Postgres directly**; exactly 1 of 55 API routes is
called by n8n over HTTP. Every validation in the service is optional in practice. That single fact
produced four identity formulas, the 502-HTML corruption, and the silent field drops.

---

## Part 3 — Blocked on the owner

Nothing here moves without you.

1. **Drive folders.** `מסמכים כללים` does not exist in the 577-folder tree and the service account
   cannot create it — by design, it only moves files. Create it in your Drive and share it with
   `person7@example.com`. Same for dedicated
   `synced`/`failed` folders to resolve the `drive-gdoc-warehouse` / `drive-bs` collision.
2. **`gh auth login`** — GitHub Actions status is otherwise unobtainable.
3. **A real `TELEGRAM_BOT_TOKEN`** — `.env:299` is the literal placeholder; alerting is dead.
4. **Where do the 5,555 `(בוריס)` files route?** They are wired to no registry, so "move them back to
   their to-sync folder" has no destination anyone can name for you.
5. **One repoint statement**, blocked by the permission classifier:
   `UPDATE workflow_entity SET settings = jsonb_set(...,'{errorWorkflow}',to_jsonb('errorHandler01'))
   WHERE id='indoxDocUploader01';`

---

## Part 4 — Open tasks, in dependency order

### Now (in flight)
| # | Task |
|---|---|
| 1 | **E2E suites** — 6 of 8 die with an identical "Service unavailable", reproduced 4×. Leads: G19 null sub-workflow inputs in `syncV3Main0001`; or the new `Try Lock` returning `{skipped:true}` to tests |
| 2 | **50k-row scale test** — sub-0.5s target, cold+warm, per-endpoint. Finds what breaks *before* the real backfill |
| 3 | **Gmail incremental discovery** — `historyId` likely unavailable over IMAP; `UIDVALIDITY`/`UIDNEXT` is the equivalent |
| 4 | **Gateway verification** — three rejection proofs; scope the 65 callers for rewiring |

### Next — prerequisites for the backfill
| # | Task | Why it blocks |
|---|---|---|
| 5 | **Stuck rows not re-picked** — `MISSING_TYPE` grew 45 → 91 despite the switch fix. Document *selection*, not switch logic | documents silently frozen |
| 6 | **Decouple the thumbnail** — runs inline, avg 116s / max 2,187s, gating real work | throughput |
| 7 | **`needs_review` exit path** — 72 parked, no route out | documents parked forever |
| 8 | **Rewire 65 callers to the gateway** | unmediated writes bake defects into 3 years of data |
| 9 | **Single identity + `DOUBLE` migration** — 729 rows, 4 formulas | collisions hide real documents |
| 10 | **`NEXT_RETRY_AT` / retry + dead-letter** — never worked | no recovery path |
| 11 | **Reaper for n8n `execution_entity`** — 34 stuck `running`; only ledger claims have one | leaks |
| 12 | **Deactivate 9 test workflows in production** — 3 have no trigger, retried every 256s forever | noise, wasted work |
| 13 | **Serialize `bbox n8n push`** — concurrent pushes contend and land nothing | deploy reliability |

### Then — scale and coverage
| # | Task |
|---|---|
| 14 | **Drive incremental discovery** — `startPageToken`; `sync_cursor` still empty |
| 15 | **Read path computed-on-write** — stats table, keyset pagination, precomputed months |
| 16 | **Elastic sync strategy** — `take` from queue depth + backpressure. Note `chunk` was never read from config (hardcoded 25) — now fixed |
| 17 | **Reprocess failure folders** — 10,150 files across 41 folders |
| 18 | **Backfill ~32,000 documents** — only after 5–10 |
| 19 | **Workflow uniformity + remaining gates** — G42/G43/G44, switch-fallback, direct-write |
| 20 | **Observability** — per-pipe delivery rate with zero-alert; source-count-vs-previous. Would have caught the 43,326 hidden files and the pipe that delivered 2 documents in its life |

### Honest ceiling
**3,000/hour is not reachable with this architecture.** Scheduling ceiling is 800/hr (`Take X` bounds
by `chunk`, not `take`); realistic worker-pool ceiling 230–380/hr. Reaching 3,000 needs dozens of
worker slots, a drive service that does not die at 256 MiB, and host RAM for both — **infrastructure,
not workflows**. Sustained 5,000/month (~7/hr) is very reachable.

---

## Part 5 — Standing QA rules

Earned the hard way today.

- **Snapshot `sync_registry` before every QA run and diff after.** Already caught two regressions.
- **Measure cold, not warm.** A warm number produced a premature all-clear on the sync timeout.
- **Assert effects, never appearances.** A rendered page is not a pass; page 2 is proven by *changed
  row ids*.
- **Never a fabricated 0** — `null` + `*_computed:false` when unmeasured.
- **Every gate must be proven able to fail.**
- **Deploy only via `bbox n8n push`** — a raw `import:workflow` deactivates workflows and does not
  reach a running instance until restart.
- **One push at a time.**

---

## Definition of done

All 7 registries resolve and are manageable · every 6-month-window document present in INDOX or
excluded by a stated rule · a document dropped into any source reaches `COMPLETED` unattended ·
sustained 5,000/month with elastic burst · every UI endpoint under 40s cold, table interactions fast
at 50k+ · no unmediated write, no second identity, no silent drop, no fabricated count · gates and CI
green · no QA run mutates live config · and a dashboard that would have caught both the 43,326 hidden
files and the pipe that delivered two documents in its lifetime.
