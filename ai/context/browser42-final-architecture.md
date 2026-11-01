# Browser42 Final Architecture — the end state for delegated browsing

2026-08-04 · status: IMPLEMENTED (slice A+B+C+D shipped, dual-Mako proof pending) · supersedes the fix-one-thing-at-a-time loop
Evidence base: the durable journals of all 13 Mako tasks (`data/browser42/tasks/mako-*`),
the sub2/sub3 monitored waves of 2026-08-04, and the accepted-result ledger (0 accepted Mako
delegations ever). Every claim below cites a journal line.

Implementation log (this commit): watchdog rewritten to the activity clock (queue_timeout /
stall_timeout / total-from-first-activity), `transition()` refreshes stage `entered_at` on every
re-entry and records `first_activity_at`, runner v2 (bounded queue wait, read-command slot
bypass, subprocess kill on timeout, cap 4), any-concurrency span emission (`src: browser42`
lane in console.localhost > כל מקביל), `task goal` platform-side executor, host-side
`task watch <slug>`. Focused suite: 36/36 green.

2026-08-04 (later): a fifth mechanism, **F5, was the actual blocker behind every
"CDP unavailable / asyncio loop" goal failure** — a nested Playwright connect. `task_goal`
calls `task_connection()` → `connect()` (starts Playwright connection #1; its event loop stays
marked *running* inside the suspended dispatcher greenlet — that is how the sync API blocks),
then calls `task_action()`/`task_verify()` → `task_connection()` → `connect()` **again**.
`sync_playwright().start()` → `PlaywrightContextManager.__enter__` finds the still-"running"
loop and raises *"Playwright Sync API inside the asyncio loop"*. This is why `status` (never
connects) and `start` (connects once) always worked while only the goal path (which nests
connects) failed. Fix: a **process-global cached CDP connection** in `connect()` — one
`sync_playwright().start()` per CLI process (each CLI command is a one-shot Popen), reused
across `task_connection()` calls, with `is_connected()` self-healing and a
`playwright.stop()` on a started-but-unconnected attempt so a poisoned loop can't poison the
retry. Also added watchdog → any-concurrency `stall:<reason>` spans and tab-census / >4-tab
CLI warnings. Suite now 52/52 green.

2026-08-04 (rich timeline): the goal path previously emitted only one collapsed `goal`
command span per task, so the console timeline showed two thin bars instead of the actual
parallel browsing. Added `span_stage()` — `task_goal` now emits a fine-grained span per
browsing stage (`goto` → `settle` → `scan` → `extract` → `screenshot` → `verify` →
`finish`) onto the same `tab:<slug>` lane, each carrying its own wall duration and stage
detail (container tag/nth/links/hits, verify ok/records). The timeline now renders the full
interleaved browsing sequence of both parallel tasks. Suite remains 52/52 green.

2026-08-04 (CDP never-dies stack): the second dual run wedged Chrome for good — a leaked
run-1 tab plus two new ad-heavy mako tabs saturated the software compositor on Xvnc
(`CompositorAnimationObserver active 66s`, CDP 502s), and nothing recovered it. Root
causes fixed structurally, not symptomatically:
1. **Verified release** — `task_finish` used a bare `except: pass` around the broker
   close; now `release_tabs()` closes, re-checks via `list`, retries once, and the reaper
   is the second line of defense.
2. **Reaper terminal sweep** — the reaper spared every `b42g:<slug>` tab forever; now a
   tagged tab whose `/data/tasks/<slug>/task.json` state is terminal
   (finished/rejected/stalled/closed/failed) is reaped (re-read right before close so a
   same-slug restart can't lose a fresh tab). `/data` is mounted into the reaper.
3. **Hard backpressure** — `task_start` refuses allocation above `HARD_TAB_CAP=6` live
   tabs with `browser_tab_pressure` instead of silently adding renderers until Chrome
   chokes.
4. **CDP self-heal watchdog** — a supervisor loop in start-browser.sh probes
   `:9222/json/version` every 10s; 6 consecutive failures (sustained outage, not a
   page-load spike) kill PID 1 for a clean Docker restart (profile volume keeps logins;
   stale singleton locks are cleared on boot; reaper reconnects). A wedged Chrome now
   recovers in ≤ ~105s instead of staying dead until a human notices.
5. **Runner headroom** — 256M→512M / 0.25→1 CPU: two concurrent goal CLIs thrashed at the
   old limit and stalled mid-protocol.
6. **Extension-authoritative ownership** — proof v3 exposed the last concurrency bug:
   `task_start`'s fallback adopted a new tab by URL match, so two parallel starts on the
   same URL let one steal the sibling's tab ("expected one live tab, found 2"). Now the
   worker exposes a `claim` action and Python asks it to claim the exact `tabId`
   allocate() returned; the URL-guess loop is gone. Ownership can no longer cross tasks.

## 1. Verdict

The platform (allocation, native tab groups, CDP, inspect/click/navigate, acceptance checks,
journals) works. The subagents were never the problem. **Three mechanisms kill or starve
correctly-working agents before they can finish**, and one more makes the whole loop slow:

| # | Mechanism | Evidence | Share of failures |
|---|-----------|----------|-------------------|
| F1 | Watchdog stage clock counts **model think time** between commands and never resets on stage re-entry | every sub2/sub3 journal ends in `stage_timeout` while `inspecting` | 4/4 sub2+sub3 tasks |
| F2 | Watchdog total budget counts **allocated** waiting time, killing tasks that are queued, not stuck | v1/v2: `task_timeout` while `allocated`, zero commands issued | 2/13 |
| F3 | Runner concurrency cap (2) is shared between subagents AND parent monitoring commands | 2 agents + monitor polling share MAX_CONCURRENT=2; `runner_busy` starves one agent | latent in all waves |
| F4 | First-command latency (allocation + page load + queue) is 82-475 s, then each step costs one full model turn (82-604 s gaps in journals) | journal timestamps | why nothing is "lightning fast" |

The proof that the agents can browse: `mako-medical-20260804-sub2` inspected the home page
(12 containers/40 controls), clicked the health channel, reached
`https://www.mako.co.il/health?partner=ChannelHeader`, inspected the results
(3 containers/10 controls) — then was killed by F1 **4 seconds after its last successful command**.

## 2. The fix stack (what actually ships)

### A. Watchdog semantics rewritten — the stage clock follows *activity*, not stages

The watchdog stops asking "how old is this stage" and starts asking "how long since this task
last did something". Concretely:

- **Activity clock.** A task is stalled iff `now - max(heartbeat_at, stage_transition_at,
  command_completed_at) > STALL_SECONDS`. Every successful runner command already updates
  `heartbeat_at` (transition() does this today) — the bug is that the watchdog compared against
  `stage_timings[stage].entered_at`, which is set with `setdefault` on first entry and never
  refreshed on re-entry (inspecting→acting→inspecting kept the old entered_at).
- **Stage re-entry refreshes.** `transition()` drops the `setdefault` and always writes
  `entered_at = now` when the stage changes (including re-entry).
- **Total budget starts at first activity**, not at allocation. `allocated` is a queue, not work.
  The total clock runs from the first `inspected`/`acted` event. Queued tasks can never
  `task_timeout` — they can only be cancelled by the caller or reclaimed after a long
  no-activity window.
- Budgets stay env-driven; defaults sized for delegated cheap models: stall 300 s (one slow
  model turn + margin), total 1800 s, stage budget removed entirely (activity clock replaces it).

### B. Runner ownership — one reserved slot per task, monitoring never contends

- `MAX_CONCURRENT` rises to 4 (2 task slots + headroom), and **task commands from the owning
  agent bypass the semaphore contention with monitoring**: `status`/`inspect`-style read commands
  from the parent use the runner's cheap path, or read `task.json` directly via the CLI (no
  runner round-trip) — monitoring never takes a work slot.
- Interrupted requests (client ^C / timeout) release their slot immediately: the runner tracks
  the subprocess and cancels it on client disconnect instead of holding the slot for the full
  request budget.
- `runner_busy` becomes a **queue with position**, not a hard reject: the client waits up to
  30 s for a slot and reports its queue position, so an agent never silently gives up.

### C. Speed — make the common path platform-side, keep the model for judgment

Per-step model turns (82-604 s each in the journals) are the wall-time killer, and no budget
tuning fixes that. The architecture splits the loop:

- **Goal executor (platform-side, no model):** for the canonical extraction goal — "latest N
  items about topic T on site S" — the runner itself drives
  `goto → wait-for-load → inspect → extract top-N → screenshot → verify`, using the same
  primitives the agents use. This is seconds, not minutes, and is deterministic.
- **Model loop stays as the general fallback:** anything the goal executor cannot classify
  (multi-step flows, logins, novel UIs) still runs through inspect/act/extract with the
  corrected watchdog. The agent's first move becomes "try goal mode; escalate to step mode on
  classified failure".
- **First-load is platform-owned:** `task start` does not return `allocated` until the page has
  fired `domcontentloaded` (Playwright `goto` already waits), so the agent's first `inspect`
  sees a loaded page and the 82-475 s first-command gap collapses to model think time only.

### D. Liveness contract — a vanished agent is detected and replaced, not mourned

- The owning agent must issue *some* command (including `heartbeat`) within `STALL_SECONDS`;
  the activity clock (A) enforces this for free.
- The parent monitor (or the caller) gets one new CLI verb: `./bbox b42 task watch <slug>` —
  tails `events.jsonl` and prints state changes; it replaces ad-hoc polling and never touches
  the runner.
- On stall, the task is reclaimable: `task start` with the same goal reuses the allocated group
  (the committed get-or-use path, `2a479aee`) so a retry does not pay allocation again.

## 3. Invariants the final system must hold

1. Only an accepted `finish` counts as success (unchanged).
2. A task that issued a command within the stall window is never killed, whatever stage it is in.
3. A queued (`allocated`) task is never killed by a wall clock.
4. Monitoring commands never compete with owning agents for runner slots.
5. The canonical extraction goal completes without any model turn (goal executor).
6. Every kill writes a classified failure code + the journal line that triggered it.
7. Retry reuses the allocated group and loaded page (no re-allocation cost).

## 4. Rollout (one coherent slice, then proof)

1. **Watchdog + transition fixes** (A): rewrite the sweep to the activity clock, refresh
   `entered_at` on re-entry, total-from-first-activity; extend `test_task_watchdog.py`
   (re-entry stall regression, allocated-never-times-out, activity-resets-clock).
2. **Runner slot model** (B): cap 4, monitoring off the work slots, queue-with-position,
   interrupt cleanup; extend `test_task_runner.py`.
3. **Goal executor** (C): `task-runner.py` gains `goal` command (canonical extraction),
   `task start --goal` shortcut; unit tests against a stub page.
4. **Watch verb + reclaim** (D): `task watch`, retry-reuses-group.
5. **Proof:** the dual-Mako subagent wave (AI + medical, 2 in parallel, monitored with
   `task watch`), both delegated, both must reach accepted `finish`. Then the 10× pair gate
   from the release plan.

Estimated size: steps 1-2 are ~150 lines + tests; step 3 is ~200 lines; step 4 is ~60 lines.
No new services, no compose changes beyond env defaults.

## 5. What this does NOT change

Native Chrome Tab Groups, the extension ownership model, acceptance checks, the durable
journals, the broker, the reaper. All of those are proven by the sub2 journals and stay as-is.
