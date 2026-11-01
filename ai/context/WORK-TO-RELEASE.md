# WORK TO RELEASE — the single executable plan

**2026-08-06.** Every objective from the owner's ~100 messages, consolidated. **Supersedes all prior
plan documents** — `THE-PLAN.md`, `THE-PLAN-V2.md`, `MASTER-PLAN-*`, `INDOX-UNIFIED-N8N-SPEC.md`,
`INDOX-SCALE-ARCHITECTURE-FINAL.md`, `EXTRACTION-REFACTOR-PLAN.md`,
`STATE-MACHINE-CHANGE-SURFACE.md`. Those remain as reference; **this is the work list.**

Rule: nothing here is "planned". Every row is either DONE, IN FLIGHT with an owner, QUEUED with a
trigger, or BLOCKED ON OWNER with the exact action needed.

---

## 0 · Blocked on the owner — nothing moves these but you

| # | Action | Blocks |
|---|---|---|
| B1 | Create `מסמכים כללים` in your Google Drive + share with `person7@example.com`. Same for dedicated `synced`/`failed` folders. | Registry #4; the `drive-gdoc-warehouse`/`drive-bs` shared-destination collision |
| B2 | `gh auth login` | GitHub Actions status is otherwise unobtainable |
| B3 | A real `TELEGRAM_BOT_TOKEN` (`.env:299` is the literal placeholder) | Telegram alerting — being made optional/off-by-default meanwhile |
| B4 | Approve: `psql -f scripts/ops/migrations/2026-08-06_sync_ledger_created_at.sql` | Backlog-depth-over-time and time-to-delivery metrics |

---

## 1 · DONE and verified

Drive pagination (**43,326 of 78,651 files were hidden**) · `shared_folders`/`folders` caps ·
mail `hasAttachment` + the `_dec` crash · label engine INBOX-only scope (**0 vs 115 results**) ·
mail triage indicator · mail deposits landing real client documents (`drive api` errors **8/15min →
0**) · async delivery (`syncV3Unit0001` p95 **829s → 5.6–38s**, 61% cancellations gone) · 6 HIGH
backend caps · endpoints (`/sync/status` **>90s → 0.05s**, `/sync/items` **46.7s → 4.1s**) ·
INDOX table: pagination, inline STATUS round-trip, month badges (**236 → 1,507 exact**), all 8
registries · document page honest states · **1,503 rows** of 502-HTML purged · DONE column ·
`errorWorkflow` dangling **21 → 1** + root cause in `hooks/push:507` · stuck-claim reaper ·
`seed.sh` insert-only + 18 landmine keys removed + gate G40 · 50,000 synthetic rows removed ·
incremental Gmail discovery built & proven (**12.1s → 1.7s**, exact set-equivalence) ·
**4h05m collapse root-caused** (`assignPairedItems` TypeError in `mode:'each'`) + lock renewal ·
zombie watchdog · machine-health guard · ~30 gates + 11 self-tests.

---

## 2 · IN FLIGHT — running now

| Stream | Deliverable |
|---|---|
| Reprocessing | All 6-month failed docs → `to_sync` (drive folders + mail fail tags). One-doc proof → 20 → batches |
| Read model | Dashboard + sync UI **sub-0.5s**; counts maintained on write, keyset pagination, no fabricated zeros |
| Auto-layout | Deterministic overlap-free node positions, all workflows + gate |
| Tags + Telegram | App tags on all ~78 workflows; TG optional, default off, placeholder auto-detected |
| Thumbnail | Delete `indoxV2GenerateThumbnail01`; link from the apitools upload (**−116s of a ~200s budget**) |
| E2E harness | `bbox indox demo` blueprint; apitools `POST /docGen`; **1,000-doc proof before 50k** |
| Data gateway | Rejection proofs; scope the 65 caller rewires |
| Deploy hygiene | **Push lock** · `N8N_URL` scheme · wire incremental sync live · `indoxDocUploader01` verdict |
| Drive connection | Refuse unspecified connection instead of defaulting to the service account + gate |
| **Extraction Phase 1–2** | Additive columns, generated trigger schemas, settings toggles, shadow harness |
| **UI-map + E2E suites** | Fix ui-map, then per-app user stories and Playwright suites, run until green |

---

## 3 · QUEUED — with explicit triggers

| # | Task | Starts when |
|---|---|---|
| Q1 | Extraction Phase 3–4: AI+local in both phases, selection → `VAL` | Phase 1–2 lands |
| Q2 | Extraction Phase 5–6: cutover, then drop `SELECTED_*`/`SELECTION_*` (43–88% populated — migrate, don't drop) | shadow comparison passes |
| Q3 | `DOC_ID` + `TOTAL_AMOUNT` consolidations; `FROM_OFFICE`→`FROM_WAREHOUSE` (91% populated) | Phase 1–2 lands |
| Q4 | Rewire 65 callers to the gateway — **plus the 4th ungated path**: `PATCH /repos/<repo>/documents/<id>` writes straight to PostgREST with no allow-list and G42 cannot see it | gateway proofs pass |
| Q5 | Single identity; `SHORT_DOC_ID` (4 formulas) → display-only; re-adjudicate 698 `DOUBLE` | Q3 lands |
| Q6 | **Build** retry scheduling — `NEXT_RETRY_AT`/`RETRY_COUNT` have **zero writer nodes**; never implemented, not merely dropped | Phase 1–2 lands |
| Q7 | `needs_review` exit path (72 parked) | reprocessing proves the loop |
| Q8 | Drive incremental discovery (`startPageToken`) | mail cursor wired live |
| Q9 | Consolidate **3 divergent STATUS enums in the webapp** (11 vs 16 values, plus a third pill function) | read model lands |
| Q10 | Workflow minimisation **66 → 38**: retire the v1 engine (`SyncScanner00001` returns 0s on 22/22 runs), deactivate 9 test workflows active in production, delete ~2,400 lines of dead Selection & Scoring in `Driver01` | layout + tags land |
| Q11 | Backfill ~32,000 documents | Q1–Q7 + reprocessing proven |
| Q12 | 50k E2E | 1,000-doc proof green |
| Q13 | Observability: per-pipe delivery rate + zero-alert; source-count-vs-previous | read model lands |

---

## 4 · The three defect patterns — the standard every task is held to

**A · A bounded query treated as the whole truth (~18 found).** Worst form invisible at the call
site: `PGRST_DB_MAX_ROWS=1000` silently caps every unpaged select regardless of the requested limit.

**B · The false clean.** Failure that reports success: `reachable:true` with empty counts · 21
workflows with zero execution rows · a QA harness reporting 0 characters instead of failing · a seeder
printing `ok` after an aborted write · a live badge on 41-minute-old data · **a stored URL that 404s**
(now three instances: thumbnails, the document page, the any-concurrency button).

**C · Two sources of truth.** Blueprint vs n8n DB · fixture vs live settings · declared trigger schema
vs table · 4 identity formulas · 3 STATUS enums.

**Every fix must make its class unrepresentable, not merely absent.** One accessor that cannot return
a truncated set beats fixing 18 call sites.

---

## 5 · Honest ceilings

**3,000/hour is not reachable** on this architecture — scheduling ceiling 800/hr (`Take X` bounds by
`chunk`), realistic 230–380/hr on the 16-slot pool. That needs **infrastructure, not workflows**.
**5,000/month (~7/hr) is very reachable.** Per-document cost is **~95% apitools**, contacted twice,
and the hash-**miss** path (256–302s) is the normal case for fresh documents — so backfill projections
built on the blended 142s average are optimistic.

**The tuned settings are off-limits**: `take`, `chunk`, `schedule_min`, worker count, n8n concurrency.

---

## 6 · Release gate

A document dropped into any of the 7 sources reaches `COMPLETED` unattended · every 6-month-window
document present or excluded by a stated rule · sustained 5,000/month · dashboard, table and sync
board **sub-0.5s cold at 180,000 rows** · per-app E2E suites green, asserting effects · no unmediated
write, no second identity, no silent drop, no fabricated count · gates and CI green · no QA run
mutates live config · and a dashboard that would have caught both the 43,326 hidden files and the pipe
that delivered two documents in its lifetime.
