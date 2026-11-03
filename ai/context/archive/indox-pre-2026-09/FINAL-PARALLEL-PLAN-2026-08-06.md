# FINAL PARALLEL PLAN — 2026-08-06

Supersedes every prior plan doc. Built from a verbatim read-back of owner messages **[254]–[302]**
(the last 50 transcript records; 46 genuine directives, 3 peer-agent messages, 1 `/loop` skill body).

---

## PART 0 — WHY THE STACK KEEPS DYING (answered with evidence, 2026-08-06 00:31 UTC event)

**`bbox n8n push` is not the primary cause. It never stopped working. The load profile changed.**

Evidence chain:

| Time (IDT) | Fact | Source |
|---|---|---|
| 03:20–03:21 | Containers stopped with `hasBeenManuallyStopped=true` | `journalctl -u docker` — this *was* the push |
| 03:31:45 | `systemd[1]: Starting Docker Application Container Engine...` | journal — **the daemon itself had stopped** |
| 03:31:58 | `n8n-postgres` fresh `StartedAt`, `restarts=0`, `oom=false`, `exit=0` | `docker inspect` — recreated by daemon start, not crashed |
| 03:32:03 | Postgres begins WAL redo | container log |
| 03:33:03 | `database system is ready` — **65 s redo, 390 MB WAL distance** | container log |
| 03:34:32 | Docker `ExecMainStartTimestamp` — **started AGAIN, 3 min later** | `systemctl show docker` |
| — | `pgrep -f bin/dockerd` returns empty on a later sample | the daemon is **flapping** |

Preconditions at the moment of failure:
- Host swap **5.6 GiB of 6.0 GiB consumed**; load average **15.0**.
- My own first command of the session returned `Wsl/Service/0x8007274c`.
- The repo's own `.wslconfig` documents this exact failure: *"12GB of a 15.7GB host left Windows under
  0.5GB free, at which point `wsl.exe` itself starts returning Wsl/Service/0x8007274c and every
  *.localhost route hangs."* The VM is now at `memory=10GB`, `swap=6GB`, `processors=6`.

Oversubscription, measured:
- `mailapi` limit **9.717 GiB** = *no limit* (host total)
- `chat` limit **9.717 GiB** = *no limit*
- `apitools` limit **8 GiB** on a 10 GiB VM
- `browser42-browser` **4 GiB**, plus a live Chromium tree (7+ renderer processes observed)
- `n8n` 2 GiB + 2 workers × 2 GiB + 3 task-runners × 1.5 GiB + postgres 3 GiB

Declared limits exceed physical RAM several times over, and two services are uncapped.

**Mechanism:** concurrent Chromium E2E + load tests + n8n workers at concurrency 8 + ~6 background
agents each shelling into `docker`/`psql` → VM hits its 10 GB ceiling → swap saturates → Windows loses
headroom → `wsl.exe` degrades → Docker daemon restarts → **every container restarts** → postgres does
65 s of crash recovery → every in-flight n8n execution is orphaned and mislabeled
*"Workflow did not finish, possible out-of-memory issue."*

**This is the single root cause behind the whole night's saga:** the phantom OOM, the 250 `crashed`
vs 14 `success` on `SyncProcGDoc0001`, and all four killed proof attempts. The push freeze was aimed
at the wrong target.

**Correction to my own earlier calls:** I attributed attempts 1–3 to `bbox n8n push`. Push *does*
restart the stack and did kill some of them — but tonight's event happened with **zero push processes
running**, which proves a second and larger cause that the freeze does not cover.

---

## PART 1 — READ-BACK: EVERY OBJECTIVE IN MESSAGES [254]–[302]

Grouped, de-duplicated, with disposition. **D**=done+verified · **F**=in flight · **T**=todo · **B**=blocked

### A. Coverage — the actual client outcome
| # | Objective | Msg | St |
|---|---|---|---|
| A1 | 100% of hacohen mail (each mail + multiple attachments) + drive (thousands incl. failed) reaching `COMPLETED` | 262 | B |
| A2 | ~3,000 docs/month expected, no gaps — *measured universe is ~32,000 over 6 months (~5,300/mo)* | 262 | B |
| A3 | Move 5,555 `(בוריס)` docs from past 6 months back to `to_sync`; same for mail fail tags | 287 | B |
| A4 | `OldDocumentMonthsBack` = 6 **and** it must bound sync discovery | 296 | F |
| A5 | Everything from past 6 months synced | 287 | B |
| A6 | `indoxDocUploader01` errorWorkflow repoint the classifier blocked — investigate, must work with local drive indox profile | 287 | T |

### B. Extraction + state machine refactor
| # | Objective | Msg | St |
|---|---|---|---|
| B1 | Exactly **2** extraction steps: base + per-type | 277 | F |
| B2 | **Each does BOTH local and AI in the same step**, per settings | 277, 301 | F |
| B3 | Both write `AI_VAL` + `LOCAL_VAL`; selection sets plain `VAL` | 277 | F |
| B4 | Delete all `SELECTED_*` columns | 277 | F |
| B5 | AI prompt derived from the local JSON query — one definition per value | 277 | F |
| B6 | Settings toggles: ai on/off, local on/off, model, other configurables | 278 | F |
| B7 | BS follows the same flat pattern (local planned later) | 283 | F |
| B8 | `COMPANY_DOC_ID` + `INVOICE_ID` → single `DOC_ID` | 283 | F |
| B9 | `DOC_TOTAL_AMOUNT` → `TOTAL_AMOUNT` | 283 | F |
| B10 | Every `FROM_OFFICE` → `FROM_WAREHOUSE` | 284 | F |
| B11 | Deep-scan all columns — tight in final version | 283 | F |
| B12 | Deep-scan full codebase for all state machine changes | 285 | D |
| B13 | Mirror the 527/527 doc-extraction two-stage pattern, same settings queries | 296 | F |
| B14 | Whole plan in **30 minutes**, not weeks | 296 | F |

### C. Scale, throughput, stability
| # | Objective | Msg | St |
|---|---|---|---|
| C1 | Maximise resources; always stable, always ready for extreme load | 273 | T |
| C2 | Throughput: 3.5 docs/hr is unacceptable — find what's clogging | 267 | F |
| C3 | Do **not** touch tuned `take`/`chunk`/`schedule_min`/concurrency | 279 | — |
| C4 | Research best practices: scaling, syncing, processing, fast dashboards | 274 | D |
| C5 | Architecture for 5,000+/mo × 6, later 5,000×12×3 | 267 | T |
| C6 | Monitor the timeline, close all empty gaps | 275 | F |
| C7 | Service account only *moves* files; never uploads. Mail uses local drive | 267 | D |
| C8 | 50k E2E: 25k local mail engine (24k gdocs/1k bs) + 25k second source, 1/2/3 docs per mail, all generated, all reach `COMPLETED` automatically | 272 | B |
| C9 | Clean the 50k fake rows | 280 | D |

### D. Read path / UI
| # | Objective | Msg | St |
|---|---|---|---|
| D1 | Dashboard **sub-0.5 s** under any load | 280 | F |
| D2 | Sync UI **sub-0.5 s** full status | 280 | F |
| D3 | Items board "much more robust and best practiced" | 281 | T |
| D4 | "Open execution" button in any-concurrency execution previews | 280 | T |
| D5 | Fix https-on-localhost link from open-execution | 288 | T |
| D6 | `/sync/items` + `/sync/status` under the 40 s budget | 259 | D |
| D7 | Highest-standard, ERP-grade, fully integrated, interactive UI | 267 | T |

### E. n8n hygiene / consolidation
| # | Objective | Msg | St |
|---|---|---|---|
| E1 | Remove `indoxV2GenerateThumbnail01`; thumbnail link from apitools upload step | 275 | F |
| E2 | Clean all old thumbnail steps and related | 275 | F |
| E3 | Thumbnail populated via `ACTION_RESTART`, like any state change — not a bespoke backfill | 258 | D |
| E4 | `COMPANY_ID` → Upload **OR** Get `API_TOOLS_ID`; never re-upload, always hash-check | 276 | T |
| E5 | All workflows auto-laid-out ("brush" button) | 289 | D |
| E6 | TG error report env-toggleable and optional | 290 | D |
| E7 | Every workflow tagged with its app; all tags consolidated | 290 | D |
| E8 | All logic unified in n8n, single data/API pattern, "pure as gold" | 267 | T |
| E9 | Fix the flagged error + deep-scan all other failed executions | 296 | F |
| E10 | Research official n8n dev practice (edit local files → `bbox` push) | 265 | D |

### F. QA / proof
| # | Objective | Msg | St |
|---|---|---|---|
| F1 | Find *a* way to fully QA the platform (private Chrome or browser42) | 254 | D |
| F2 | Full live `ui-map` capture as prestep — 62/62 captured | 293 | D |
| F3 | Per-app Playwright E2E suites from user stories | 293 | F |
| F4 | Mail sends between users; drive upload/move/rename; indox sync→upload→watch to `COMPLETED`; settings; companies; sync board | 293 | F |
| F5 | Run until all green | 293 | T |
| F6 | Verify 50k rows render fast, window load < 0.5 s | 270 | B |

### G. Process
| # | Objective | Msg | St |
|---|---|---|---|
| G1 | Monitor all subagents — no stalls, no drifts | 256, 260, 292, 295, 298, 300 | ongoing |
| G2 | Consolidate **all** plans into one parallel work-to-release plan; no unaddressed plans | 293 | this doc |
| G3 | Loop: 2 min stall check, 15 min full parallel replan | 286 | ongoing |
| G4 | Stop restating blockers I can resolve myself | 294 | — |
| G5 | Continue fully autopilot, all in parallel | 255, 268, 291 | ongoing |

---

## PART 2 — THE PARALLEL PLAN

### LANE 0 — HOST STABILITY *(gates every live proof; nothing else is trustworthy until this holds)*

| Step | Action | Done when |
|---|---|---|
| 0.1 | Cap the two uncapped services (`mailapi`, `chat`) with real `mem_limit`s | no container reports host-total as its limit |
| 0.2 | Cut `apitools` 8 GiB → ~2 GiB (observed usage 60–754 MiB) | limit ≤ 2 GiB, no OOM across a full baseline |
| 0.3 | Sum of limits ≤ ~1.5× physical, not 4× | arithmetic check in a gate |
| 0.4 | **Admission control**: refuse to start Chromium E2E / load tests when swap > 50% or load > 8 | guard script blocks a heavy job under pressure |
| 0.5 | Serialize heavy consumers — Chromium E2E must never run during a pipeline proof | documented + enforced by 0.4 |
| 0.6 | Watchdog records daemon start events so a restart is never again misread as OOM | `docker` `ExecMainStartTimestamp` logged each pulse |
| 0.7 | **Verify: 2 h with zero daemon restarts and zero postgres recoveries** | journal clean |

### LANE A — EXTRACTION + STATE MACHINE  *(agent `a4058cf69`, in flight)*
B1–B14 above. Files on disk now; deploy gated on Lane 0.
Acceptance: 2 steps only · both run local+AI per settings · `AI_VAL`/`LOCAL_VAL`/`VAL` populated ·
zero `SELECTED_*` remaining · `DOC_ID`/`TOTAL_AMOUNT`/`FROM_WAREHOUSE` renamed everywhere ·
BS on the flat pattern · G41 switch-fallback gate green.

### LANE B — THROUGHPUT + COVERAGE
| Step | Action |
|---|---|
| B.1 | **Single-document wall-clock proof** — attempt #4, in a Lane-0-quiet window, natural scheduler only |
| B.2 | Fix `indox-manage` `RELEASE` requiring fully-qualified `<instance>/<pipe>` while `SCAN` takes the bare name |
| B.3 | Fix manual `SCAN` debounce silently no-opping (the sync board's "run now" lies) |
| B.4 | Fix `Try Lock` skip returning `success` (task #66) |
| B.5 | `OldDocumentMonthsBack` = 6, bound discovery (A4) |
| B.6 | Move 5,555 `(בוריס)` + mail fail tags back to `to_sync` (A3) |
| B.7 | `drive-boris-recovery` registry, newest-first, pre-seed 405 already-`COMPLETED` |
| B.8 | Backfill ~32,000 docs, timeline gaps closed (C6) |
| B.9 | `indoxDocUploader01` errorWorkflow repoint (A6) |

### LANE C — READ PATH / UI
D1–D5, D7 above, plus console gunicorn + fetch dedupe + gzip (**agent stalled — re-dispatch**).
Note: sub-0.5 s is not reachable end-to-end today; measured floor ~2.4 s direct / ~7.0 s through the
shell. The CQRS read model gets the *server* side under 0.5 s; the remaining gap is bundle+shell and
needs its own step. I will not report this green on a server-only measurement.

### LANE D — N8N CONSOLIDATION
E1, E2, E4, E8 · 66 → 38 workflows · retire v1 engine · retire `indoxDocUploader01` + chat fallback ·
delete foreign `sG9bU0ER2yVitKXR` "zz-scratch-gateway-probe (delete me)" (**active in production**) ·
deactivate 8 active test workflows · `NEXT_RETRY_AT`/`RETRY_COUNT` have **zero writer nodes** —
implement or remove · fix `imapclient.search()` missing `charset='utf-8'` (`apps/mail/mailapi/app.py:621`).

### LANE E — E2E QA
F3–F6. Per-app Playwright suites, run until green. **50k E2E runs last** — it is the single heaviest
memory consumer and cannot run before Lane 0 holds.

---

## PART 3 — HONEST CEILINGS (unchanged, restated so no one plans against fiction)

- **3,000 docs/hr is not reachable** on the current scheduler: `Take X` bounds by `chunk`, giving a
  ceiling near 800/hr; realistic sustained 230–380/hr. Reaching 3,000/hr needs a scheduler change,
  and the owner has forbidden touching the tuned batch settings — so this needs an explicit decision.
- **Sub-0.5 s full page load** is not reachable through the console shell today (~7.0 s).
- The **~32,000-document** 6-month universe is ~5,300/month, above the owner's 3,000 estimate.

## PART 4 — SEQUENCING

Lane 0 runs alone and first (it is short). Lanes A, C, D proceed on disk in parallel *during* Lane 0
— none of them need a live deploy to be written and gate-checked. The moment Lane 0 verifies, deploys
unfreeze and Lane B.1 takes the first quiet window. Lane E follows Lane B.
