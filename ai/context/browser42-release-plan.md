---
date: 2026-08-04
status: canonical-plan
tags: [browser42, agents, release, chrome-tab-groups, qa]
---

# Browser42 final release plan

## Decision

Browser42 is **not release-ready for cheap-model autonomous browsing**.

The shared-browser foundation, native Chrome Tab Groups, declarative task API, durable evidence,
acceptance gate, watchdog locking, and private runner are real. Generic canaries can finish through
the protocol. The missing proof is the product claim itself: no delegated agent has returned an
accepted `finish` through the private runner, no parallel delegated pair has passed, the domain
corpus does not exist, and lifecycle/security fault coverage is incomplete.

Do not report a browsing task as successful unless its durable result is accepted. A returned tool
call, plausible text, screenshot, or surviving tab is not success.

## Evidence boundary

This plan supersedes the implementation phases in
`browser42-agentic-browsing-lifetime-report.md`; that report remains the immutable historical
record through its ledger cutoff. This plan adds evidence observed after that cutoff:

- 14 Browser42 delegations from 2026-08-03 20:10Z onward, totaling 5,488.4 seconds of agent time;
- 19 durable protocol-era tasks: 6 accepted/finished and 13 stalled;
- accepted tasks are generic protocol or runner canaries, not delegated parallel proofs;
- both generic delegated parallel tasks stalled; one reached extraction and one inspection;
- 2026-08-04 (post-plan): after the F5 nested-connect fix, the extension-authoritative
  ownership fix, verified tab release, terminal-tab reaping, hard tab-cap backpressure,
  the CDP self-heal watchdog, and per-stage span emission, the first two accepted parallel
  delegated Mako pairs were recorded (goal-first, zero model turns, 7 records each, all
  acceptance checks true, tabs released). R5's 10x repetition gate remains open;
- the structured Mako tasks reached allocation/inspection at best and none finished accepted;
- focused Browser42 tests pass 24/24 after the watchdog regression was added;
- G35 passes: 54 operative files contain no incident-fixture knowledge.

The transcript identifies the `Browser42` agent but does not expose the underlying model identity.
Therefore this evidence cannot honestly compare named cheap models. It measures the tested agent
configuration and orchestration. A model-specific claim requires recording model/version for each
run in the task journal before execution.

## Current scorecard

| Area | Status | Evidence | Release gap |
|---|---|---|---|
| Shared headed Chromium/profile | Complete | Live runtime and historical proof | Fresh-install proof remains |
| Native labeled/colored groups | Complete | Extension uses official Chrome APIs | Restart/fault matrix remains |
| Exact tab ownership | Implemented | Generation plus owned tab IDs; exact-tab verify | Cross-task adversarial tests remain |
| Popup inheritance | Implemented | `openerTabId` adoption and popup policies | Runtime fault matrix remains |
| Declarative task CLI | Implemented | Start, inspect, act, extract, capture, verify, finish | `scroll` and recovery ergonomics remain |
| Durable task lifecycle | Implemented | Atomic writes, locks, revisions, terminal-state guard | In-flight cancellation/monitoring remains |
| Acceptance-only result | Implemented | Schema, record fields, ownership, URL, screenshot hash | Image nonblank validation needs strengthening |
| Private task runner | Implemented, unproven at scale | Runner canary accepted | No delegated or parallel runner proof |
| Watchdog | Implemented | Total, stage, heartbeat classifications | Diagnostic capture and runner cancellation remain |
| Site neutrality | Passing | G35: 54 files | Keep as a permanent gate |
| Least privilege | Partial | Agent has only execute/read; prose forbids bypasses | No verified pre-tool enforcement |
| Shared-browser CDP safety | Partial | `Browser.close` blocked | Broader destructive-method policy absent |
| Multi-domain corpus | Missing | No release corpus | Build and run before model claims |
| Parallel proof | First accepted pairs (2026-08-04) | Two goal-first delegated Mako pairs accepted with released tabs | Repeat 10x per R5, then 5- and 10-task waves |

## Cheap-agent assessment

The 14 post-ledger delegations scored **0 accepted finishes**. Short attempts correctly failed
closed; long attempts showed poor recovery and termination discipline. Durable state proves some
agents could preserve a slug, allocate a task, inspect, and occasionally extract. It does not prove
they could complete evidence and acceptance.

| Dimension | Observed verdict |
|---|---|
| Protocol entry | Inconsistent; several prompts produced no durable task |
| Immutable slug discipline | Usually correct once allocation succeeded |
| Handle-only actions | Partial progress, no accepted delegated completion |
| Navigation/extraction | One generic parallel task extracted one record; insufficient |
| Evidence and finish | Failed: no post-ledger delegation reached accepted `finish` |
| Fail-closed behavior | Good in short rejected/stalled attempts |
| Recovery behavior | Poor; several attempts ran 5–24 minutes without acceptance |
| Parallel autonomy | Failed; both generic parallel siblings stalled |
| Isolation | No accepted cross-task proof; no known accepted sibling mutation either |
| Model comparison | Impossible because model identity was not journaled |

This does not establish that cheap models are intrinsically incapable. Earlier runs were polluted by
shared terminal output and shell mechanics; later structured runs predated or did not delegate
through the final private-runner path. The fair test begins only after the runner and model identity
are both observable in each task journal.

## Release invariants

1. One persistent headed Chromium/profile; no delegated browser launch.
2. Every task owns one native group and an extension generation; every created descendant is
   adopted, denied, or classified within a bounded interval.
3. Every operation resolves extension-owned IDs and rechecks ownership before and after mutation.
4. The model emits intent and handles only. It never emits Playwright, selectors, CDP, shell
   wrappers, HTTP clients, or teardown mechanics.
5. Runtime code is site-neutral. Site names and workflows exist only in external fixtures/results.
6. Task state is monotonic. `stalled`, `rejected`, and `accepted` cannot be resurrected.
7. The runner owns timeouts, retries, cancellation, heartbeat, and diagnostic capture.
8. Only an accepted `finish` is reportable success; all other outcomes carry a stable error code.
9. One task cannot inspect, mutate, close, capture, or finish another generation.
10. Reconciliation leaves no stale manifests, storage ownership, duplicate tabs, or unowned task
    descendants.

## Dependency-ordered work

### R0: freeze measurement and identity

1. Add runner request ID, agent name, model/version, prompt hash, task slug, and parent wave ID to
   `task.json` and every terminal result.
2. Create a versioned 20-prompt corpus spanning unrelated domains, RTL/LTR, search, forms,
   pagination/scroll, popup, shared-cookie login, table/list extraction, download, and screenshot.
3. Add a deterministic corpus driver that accepts a model/configuration explicitly and reads only
   durable accepted results.
4. Publish per-stage wall time, retries, error code, and accepted tasks per wall-clock minute.

Exit: every run is attributable and reproducible; the current build fails the corpus for known
reasons rather than silently skipping unsupported cases.

### R1: make runner isolation observable and bounded

1. Add `/healthz`, queue depth, active request count, request IDs, and structured timeout details.
2. Align source, Compose, client, stage, and operation budgets. The current effective runner is
   120 seconds, its source fallback is 40, client is 130, and watchdog stage budget is 30; this must
   become one documented policy rather than four clocks.
3. Cancel the manager subprocess when a stage budget expires and atomically preserve its diagnostic
   state. A watchdog classification must never leave expensive work running invisibly.
4. Add startup readiness so extension warmup is a health state, not a caller retry after an
   arbitrary sleep.
5. Prove two simultaneous requests have isolated stdin/stdout, request IDs, state, and cancellation.

Exit: 100 repeated two-request transport canaries have zero mixed output, cross-task state, orphan
processes, or unclassified timeout.

### R2: complete lifecycle ownership

1. Replace action-refreshed heartbeat alone with a platform-owned monitor recording URL, page
   signature, owned tab set, generation, CDP latency, screenshot state, and resource counts.
2. Define progress mechanically: stage transition or expected page-signature change. Repeated
   inspection of an unchanged page is not progress.
3. Capture a viewport diagnostic and compact observation on failure before marking terminal state.
4. Reconcile extension storage, manifests, groups, and task state after worker, broker, browser, and
   runner restarts.
5. Route all close/GC paths through broker ownership and verify no unowned descendants remain.

Exit: the lifecycle fault matrix passes with terminal-state monotonicity and no stale ownership.

### R3: close action and acceptance gaps

1. Add declarative scroll/infinite-scroll support and bounded wait conditions based on page
   signatures, result count, URL, visibility, and text.
2. Centralize classified retries for transient CDP errors, navigation commit/load divergence,
   detached handles, popup adoption, and screenshot fallback.
3. Validate screenshots by decoding dimensions and pixel variance in addition to path and SHA-256.
4. Make extraction requirements explicit for count, required fields, URL policy, uniqueness, and
   visible-source provenance.
5. Return compact legal recovery actions with every recoverable error; permit at most one
   model-level recovery for a classified failure.

Exit: scripted handle-only clients pass every non-authenticated corpus capability without generated
browser code or site adapters.

### R4: enforce safety outside the prompt

1. Implement and test an explicit CDP method policy covering browser/context/target destruction,
   not only `Browser.close`.
2. Bind runner and broker requests to slug plus generation capability; reject stale generations and
   another task's tab/group IDs.
3. Implement an actual pre-tool policy for the Browser42 agent, or replace generic `execute` with a
   dedicated Browser42 task tool. Prose restrictions are not a security boundary.
4. Enforce URL scheme policy, download containment, artifact path traversal protection, journal
   redaction, and task-directory write containment.
5. Add adversarial tests for prompt injection, bypass tools, browser launch, direct networking,
   cross-slug actions, destructive CDP, and secret leakage.

Exit: adversarial prompts cannot bypass Browser42, mutate sibling/shared state, or write outside the
task artifact directory.

### R5: prove agents and parallelism

Run in this order; do not fan out after a failed prerequisite:

1. One generic delegated runner canary per designated model/configuration.
2. All 20 corpus prompts serially, repeated three times per model/configuration.
3. Ten two-task waves: mixed-domain, same-domain, and identical-prompt/unique-slug.
4. Five-task waves, then ten-task waves, while recording queue, CDP, CPU, memory, renderer, and tab
   pressure. Increase resources only when measured saturation, not protocol failure, demands it.
5. External Mako proof fixture: AI and medical five-article siblings from short prompts, repeated ten
   times. Keep all site knowledge outside runtime and generic tests.

Exit per designated model/configuration:

- at least 95% accepted corpus tasks across three repetitions;
- 100% of reported successes backed by accepted `finish`;
- at least 9/10 complete accepted Mako pairs;
- zero cross-task mutations, false success, stale task tabs, duplicate task tabs, or unowned task
  descendants;
- no unclassified attempt exceeds 90 seconds.

### R6: product and install release

1. Decide and document standard Chromium versus extension-capable patched Chromium.
2. Align app, extension, broker, schema, runner, and CLI protocol versions.
3. Move stable image installation before volatile first-party guard/source layers.
4. Remove stale comments, implicit-session docs, unused constants, and obsolete proof tabs/artifacts
   after preserving the lifetime report and ledger.
5. Run a fresh `bbox run`, automatic corpus smoke, restart reconciliation, and clean-state audit on
   the supported Windows/WSL and Debian paths.

Exit: a fresh clone reaches the release gate without manual browser repair or extension warmup.

## Required fault matrix

- MV3 worker suspension, offscreen recreation, broker disconnect, runner restart, browser restart;
- stale tab/group/generation IDs, renderer crash, transient CDP failure, navigation commit without
  load, screenshot timeout, reaper sweep during allocation, popup during action;
- one task stalls while its sibling navigates, one closes while its sibling extracts, and one is
  cancelled while its manager subprocess is in flight;
- forbidden URL schemes, path traversal, another slug's IDs, destructive CDP, direct-network tool,
  prompt-requested bypass, and journal secret scanning.

Every case asserts shared browser PID/profile survival, sibling state preservation, one terminal
classification, diagnostic evidence, and zero stale/unowned task tabs.

## Latency SLO

| Metric | Warm | Cold/fault | Enforcement |
|---|---:|---:|---|
| Runner preflight | <= 2 s | <= 5 s | Reject before allocation |
| Native allocation | <= 3 s | <= 15 s | Classify startup failure |
| First useful inspection | <= 5 s | <= 15 s | Capture diagnostic |
| Generic accepted canary | <= 45 s | <= 90 s | No fan-out before pass |
| Additional sibling | <= 30 s | <= 60 s | Bounded queue and stage |
| Unclassified attempt | <= 90 s | <= 90 s | Cancel and journal |
| Model recovery | <= 1 | <= 1 | Retry only classified failure |
| Reported-success acceptance | 100% | 100% | Fail closed |

## Exact release command gate

The release gate must be one repository command that runs schema/unit tests, G35, Compose compile,
fresh runner health, lifecycle/security faults, the corpus, parallel waves, and the clean-tab audit.
It must emit a machine-readable manifest with source revision, runtime image digests, browser and
extension versions, model identities, result hashes, acceptance rates, latency percentiles, and tab
cleanup counts.

Until that command passes, Browser42 may be described as an implemented structured browsing
harness with accepted generic canaries. It must not be described as cheap-model-ready, generally
autonomous, or parallel-release-ready.