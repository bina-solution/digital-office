# Automatic progress — what a step produces, and what happens when it produces nothing (DGO-1294)

**Status:** a design for the owner's approval. Nothing is re-enabled by it. Item `acost-002` in
`hp-dgo:apps/project-pln/plans/agent-cost.yaml:78-95`.

The owner (verbatim, `hp-dgo:apps/project-pln/plans/agent-cost.yaml:83`): «עדיין צריך לחשוב מלא על איך באמת לנהל
התקדמות אוטומטיצת כרגע אנחנו פשוט מנהלים הכל מהפקודה קדימה ואז אנחנו גם רואים מה בדיוק קורה». Turning the loops off is a state, not a conclusion. This answers the
three standing rules of `hp-dgo:ai/context/agent-economics.md:12-27`: nothing spends without producing a change;
₪1/day is the ceiling for anything that activates itself; no session continues itself.

Citations are `file:line` on `mac-dgo` 66a8011a. `hp-dgo:` means the file as it is on `origin/hp-dgo`.

## 0. Found first: "off" is true on one office only

- **DGO-1292's fence (73d8cee7) is only on `origin/hp-dgo`** (`git branch -r --contains 73d8cee7`). On
  `mac-dgo`, `vps1-dgo` and `dgo-stable` the clock is declared on (`apps/bina-ds/blueprint/n8n/binaSeder00001.workflow.ts:48`
  `active: true`, 07/13/21 h at :64-66), the door has no `seder-budget` refusal (`apps/bina-ds/adapter/server.mjs:713-736`),
  and `harness/profile/cordis.patch.yml` has no `goal-guard` row and no disabled `goal-round-driver`.
- **The live vps1, read-only on 2026-11-10:** `binaSeder00001` is active in n8n, with 9 successful executions in the
  last three days, the last at 05:00Z. claude-dgo is the same as mac-dgo; dell-dgo has no bina-ds workflows.
- **`binaDayRun00001.workflow.ts:46` is `active: true` on every branch, hp-dgo included.** Its "one-off" cron
  `48 16 14 10 *` (:62-64) fires every 14 October with `by: 'bina-seder'` (:103). It names no time zone, so it fires
  in the host's. On Jerusalem time (the Mac, claude-dgo) 2027-10-14 opens three cycles; on vps1 (UTC) the cycle table
  matches nothing, and on hp-dgo the door answers 409. Set inactive on mac-dgo by this item's first commit.
- **After every bina-ds update, self-update.sh tells recently active sessions to continue.**
  `apps/bina-ds/self-update.sh:372-395`, called at :605 and designed at :346-355, finds each session that wrote in
  the last 180 s. It sends that session a turn: continue, don't wait for approval, and re-arm the goal with
  `bbox agent goal <id> resume`. It is identical on every branch, hp-dgo included, and it breaks «no session
  continues itself» outright. `hp-dgo:agent-economics.md:62-63`, which says the checkout holds no keepers, missed it.
  **Fixed on mac-dgo (DGO-1792):** by default no session is sent a turn; the cut ones are named in a notice of
  their own, each with its `/go/bina?s=<id>` link. `BINA_DS_SELF_UPDATE_RESUME=send`, by name only, tells them of
  the update and to wait for a person; `apps/bina-ds/test_self_update_resume.py` holds it. Other branches take it
  by merging dgo-stable.
- **DGO-1292's no-push seder watch is already on every branch** (`2c5ed3a5`; `server.mjs:566-572`). Only the fence
  is hp-dgo's.
- **The harness ships a scheduler,** `@deepseek-ai/dsh-schedule` (`harness/profile/pnpm-lock.yaml:6149`, under
  `@deepseek-ai/dsh` at :6113); no branch disables it, and whether it is mounted is not verified.
- **Even on hp-dgo the door's fence measures nothing:** it checks only that `BINA_DS_SEDER_BUDGET_METER` is
  non-empty (`hp-dgo:apps/bina-ds/adapter/server.mjs:745-752`); any value opens it.
- **The seder skill still says «מטרה פעילה ממשיכה לרוץ מעצמה»** and opens each cycle with `create_goal`
  (`…/agent-presets/azaria/skills/seder/SKILL.md:154-156`), on every branch.

So the first work is not a new mechanism. It makes "off" true everywhere: items P0 and P1 below.

## (a) Progress — what counts as a step that moved

**Today.** The only definition in code is goal-guard's: a goal round with zero `tool/call` is empty
(`hp-dgo:apps/bina-ds/plugins/goal-guard/lib/index.js:157-169`). It catches the 841 empty rounds, but not a
round that only reads, forever. The Claude-side Stop hook already uses a stronger signal, the branch tip plus
the open-item count (`.claude/hooks/work-left.py:193-199`); `day-progress.py` counts items closed
(`apps/bina-ds/tools/day-progress.py:11,48`).

**Decision.**
- **The unit is one turn of a session that serves ONE work item,** titled the way `bbox agent do <REF>` titles
  it (`ai/context/agent-contract.md:94`). A self-activated start that names no item opens nothing: «No item,
  no round» (`ai/context/agent-routine-budget.md:16,133`).
- **This rules out the seder as it is.** Its door names no item, and its session manages many items
  (`skills/seder/SKILL.md:28-29`). So either the seder door retires, or a manager turn is defined as moved only
  when one of the items it touched moved. Which of the two is in «What the owner approves».
- **It builds on the earlier design, `ai/context/agent-routine-budget.md` (2026-10-13), and replaces none of it:**
  - per-item approval (`מאושר`) and a `תקציב:` line (§3);
  - refusal when the hub cannot be read (§4), which is the same idea as (c)'s refusal;
  - "complete is final" (§8), which S5 extends;
  - cost at every level (§6), which (d) gathers on one screen.
  Its «No item, no round» was never built; pulse.sh, which held it, is deleted (`SKILL.md:145`).
- **A turn moved** when, between its `turn.start` and `turn.end`, at least one of these changed, read at its source:
  1. **commit:** a new commit on the office branch, authored by the agent (`git log <tip-at-start>..HEAD --author`);
  2. **item:** the item's state group changed, or its `updated_at` moved because the agent wrote to it
     (`tasks show <REF> --json`: `state`, `group`, `updated_at` — `apps/project-pln/tasks.py:662-679,760-787`; the
     JSON carries no comment count, so a comment is read through `updated_at`);
  3. **file:** a write/edit tool returned ok on a path (`tool.call`/`tool.result`, `agent-contract.md:67`);
  4. **check:** a command named under the item's «קבלה» exited 0 for the first time on this item.
- **Not a step:** a turn with no tool call; a turn of reads only (status, list, grep, GET); creating or
  editing a goal; reading the budget line (`ledger.mjs --line`); a message or notice with none of 1–4;
  re-running a check that was already green.

**Measured by** a fingerprint per (item, turn): agent commits, item group plus `updated_at`, paths written,
green checks. The turn moved if and only if the fingerprint changed. One row per turn goes to
`data/bina-ds/sedarim/<day>/progress.jsonl` — `{at, session, ref, turn, ₪, moved:[…], stop?}` — in the day
folder the door already writes (`server.mjs:473-497`). The fingerprint is computed in the adapter, shaped like
the seder watch (`server.mjs:560-660`), because the adapter already holds each session's turns and reaches git and
Plane; goal-guard stays the synchronous fence inside the harness (it chose to be non-blocking,
`hp-dgo:…/goal-guard/lib/index.js:20-21`).

**Item A (`acost-004`):** the fingerprint and `progress.jsonl`, in `apps/bina-ds/adapter/`.
Proof: fixture replays. A read-only turn gives `moved:[]`, a commit gives `moved:[commit <sha>]`, and an item
start gives `moved:[item started]`. Tests are in the style of `adapter/test_seder_watch.mjs`.

## (b) The stall detector

**Today.** goal-guard stops a goal after one empty round and clamps every goal to 12 rounds
(`hp-dgo:…/goal-guard/lib/index.js:97-137`). The seder watch reports a dead or stopped cycle and sends no turn
(`server.mjs:560-576`). The 40-step cap is only "the agent's own discipline" (`…/skills/seder/ledger.mjs:24-27`,
`SKILL.md:35-39`). work-left.py lets go after 3 identical blocks (`.claude/hooks/work-left.py:134`).

**Decision.** These apply to self-driven turns only; a turn a person sent is never stopped by this.
- **S1 empty:** zero tool calls → stop at once. goal-guard rule 1 does this, but only for turns whose source is
  `{kind:'goal'}` (`hp-dgo:…/goal-guard/lib/index.js:148-154,163`). A turn in a session a door opened, and the
  self-update «continue» turn, are not goal rounds, so the adapter's watch applies S1 to every self-driven turn too.
- **S2 no change:** the 2nd consecutive turn on one item with an unchanged fingerprint → stop with `no-change`.
  One reading turn before a change is normal; two in a row is a loop.
- **S3 long turn:** a self-driven turn that reaches 40 steps is cancelled through the existing door
  (`POST /v1/sessions/{id}/cancel`, `server.mjs:783`), and its partial state is left on the item. The seder's
  40 becomes code; checking the fingerprint at every step would cost a git+Plane read per step.
- **S4 money:** the day's self-activated spend reaches the grant → stop. See (c).
- **S5 counters per (day, item), not per goal id.** Re-creating a goal resets nothing. Re-creation is how 12
  became 400, three times (`hp-dgo:apps/project-pln/plans/agent-cost.yaml:50-51`).
- **After any stop, nothing restarts it:** one notice with the code, item and link (`notifyOffice`,
  `server.mjs:460`); the item is skipped by every self-activated start until a person touches it; resuming
  is a person's act (`hp-dgo:…/goal-guard/lib/index.js:36-38`).

**Measured by** replaying `session-f7a05d7b` through S1–S5: it must stop at the first empty round (20:40:51,
₪3.60), so the ₪15.50 after it (`hp-dgo:ai/context/agent-economics.md:44`) is never spent. Stops per code per
day are counted and shown in (d).

**Item B (`acost-005`):** S1 for non-goal self-driven turns, plus S2, S3 and S5, in the adapter's progress
watch. It keeps goal-guard for goal rounds, and uses the cancel and goal doors for the stop. Proof: unit replays of S1–S5, plus the f7a05d7b replay showing the round
it stops at and the ₪ at that round.

## (c) The real budget

**Today there are two calculators, and they disagree.**
- **cost-meter** prices one session, cumulatively, and is correct on the attempt→settlement replacement, the
  peak window and the Settings rate (`plugins/cost-meter/lib/cost.js:55-86`; the rate in `pricing.js` `money()`
  :156-169 and `cost.js view()`). It has no day, and it stops nothing.
- **The seder ledger** (`…/skills/seder/ledger.mjs`) is the only per-day, cross-session meter, with three faults
  and one suspected:
  (1) its **own copy** of the prices and a fixed 3.7 rate (`ledger.mjs:35-46`), against the "no copy" claim of
  `hp-dgo:…/agent-economics.md:69-70`; (2, suspected — not yet measured against the pill) it adds **every**
  usage event (`:121-130`) though the harness writes each sample twice, attempt and settlement
  (`plugins/cost-meter/README.md:50-53`, `test/pricing.test.mjs:88-90`), which reads as a double count; (3) a
  route-less attempt is priced at Flash (`:123`); (4) "self-activated" is only a session titled `סדר …` and its
  children (`:150`, `:282-297`), so goal rounds inside a person's session are invisible to it. The ₪19.10 session
  was one such: its goal rounds were 935 of its 961 rounds.

**Decision.**
- **One meter.** It imports `cost.js`/`pricing.js` and copies nothing. It folds per request day in
  Asia/Jerusalem (as `ledger.mjs:103` does) and keeps the replacement rule. Its zstd frame reader moves in
  from `ledger.mjs:62-84`. `ledger.mjs --line`, `day-progress.py` and the door all call it.
- **Attribution per turn, not per title.** A turn is self-activated when its opening `user/message` source
  is not a person, or when its session was opened by a door (or descends from one). `source.kind==='goal'`
  is verified (`hp-dgo:…/goal-guard/lib/index.js:148-154`). A person's session is that person's money: it is
  shown, but never capped.
- **The ceiling is cumulative; the check runs per call.** The ceiling is today's self-activated total
  against `grant` (`data/bina-ds/sedarim/<day>/תקציב.json`, default ₪1, `server.mjs:447-454`). The full meter
  runs when a door opens a session; at each step end of a self-driven turn (S4) the check is that total plus
  the session's own cost-meter value since the turn began — cheap, and the same arithmetic.
- **Refusal when the ceiling cannot be proven.** The door answers `409 seder-budget` unless all hold: the meter
  read the store under 60 s ago and no session file is newer than that read; no model the day used is unpriced
  (`pricing.js:83-87`); and `spent + reserve < grant`, the reserve being two steps at the current context's
  price. This replaces the env-presence check (`hp-dgo:server.mjs:745-752`); `{"dry_run":true}` returns the proof.

**Item C (`acost-006`):** the day meter and the door's proof, in `apps/bina-ds/adapter/`. Proof: the meter equals
the cost-meter pill to the agora on 3 real sessions; an attempt plus its settlement is priced once;
`tools/seder-door-selfcheck.py` gains store unreadable → 409, grant reached → 409, under the grant → the dry
run shows the numbers.

## (d) What the owner sees

**Today** the facts are spread over six places, and none says what runs by itself right now: the pill
(`plugins/cost-meter/README.md:66-71`), the day folder (`server.mjs:473-497`), `day-progress.py`, the notice
centre, the timeline lane (which already records each turn's source and tool calls,
`plugins/timeline-lanes/lib/mapping.js:88-93,137`) and `bbox agent list` (`scripts/bbox_agent/cli.py:131-132`).

**Decision.** One screen, «מה רץ מעצמו», built from one JSON, with three blocks:
1. **Now.** Every source that can open or continue a session, with its state (off / armed / running): the n8n
   workflows that call a door, found by scanning the blueprints (today `binaSeder00001`, `binaDayRun00001`);
   the harness rows `goal-round-driver`, `command-goal`, `dsh-schedule`; self-update.sh's continue step; every
   armed goal (`summary.goal`, `server.mjs:139-158`).
2. **Today's cost.** Self-activated ₪ against the grant, from the one meter, with people's sessions shown beside it.
3. **What it changed.** Today's `progress.jsonl` rows (commits, items, files, each linked) and every stop with
   its code.

With everything off the screen reads «שום דבר לא רץ מעצמו · ₪0.00 היום». The JSON is served as
`GET /v1/self` (adapter, behind the token) and printed by `bbox agent self`.

**Item D (`acost-007`):** an interactive mock plus its screenshots first, in `digital-office/sim/` (owner's
rule 11, `AGENTS.md`). Then the route, the CLI verb and the card. Proof: on each office, the zero state shows
on the screen and in the CLI, and a source set back on (for the test, on a throwaway office) shows as armed.

## Prerequisites (no new mechanism)

- **P0 (`acost-003`): DGO-1292's off state on every office (mac, hp, vps1, claude; dell has no bina-ds).**
  - **How it lands.** Merging 73d8cee7 itself would bring 10 commits and 101 files (`git rev-list
    origin/dgo-stable..73d8cee7`), among them the HP's `platform.state.yaml` (2fc5384a), «the work found
    uncommitted» (c20aa9f4, 129 files) and the HP's identity swap (f479d740). So the fence's own files
    (goal-guard, the `cordis.patch.yml` rows, the door's refusal, `binaSeder00001` `active:false`) go to
    `dgo-stable` as their own batch item, and each office takes dgo-stable by merge (AGENTS.md
    Non-negotiable 6).
  - **Where the plan lives.** `agent-cost.yaml` and `agent-economics.md` exist only on hp-dgo. They travel with
    that batch item, so no other branch writes them a second time.
  - **What else it switches off:**
    - `binaDayRun00001` set `active:false`, done on mac-dgo with this document (DGO-1294's first commit);
    - self-update.sh's continue step (:372-395) off;
    - the `dsh-schedule` row disabled, or proven unmounted.
  - **Proof:** on each office, n8n reports both workflows inactive, the door answers 409, the image carries
    goal-guard, and a bina-ds update sends no turn.
- **P1 (`acost-008`, its own session, because a SKILL.md is an entry file — AGENTS.md "How a session works" §5):**
  bring `skills/seder/SKILL.md:138-157` in line with "no session continues itself". That removes the
  self-continuing goal and the `create_goal` opening.

## Not verified here

The live n8n `active` state and the live bina-ds image on any office (no `bbox` was run); whether
`dsh-schedule` is mounted; whether the harness RPC exposes a goal block (the adapter offers only pause, resume,
clear, complete — `server.mjs:837-840`); whether the session list carries the `costMeter` projection beside
`tokenUsage` (`server.mjs:140,155`); source kinds other than `goal`; the ledger's double count, measured
against the pill; the harness's names for its write/edit tools; where `session-f7a05d7b`'s log lives now.

## What the owner approves

1. **(a)** A turn moved only by a commit, an item change, a file written or a check passing; reading and talking do
   not count. And for the seder: retire its door (one item per self-activated session), or count a manager turn as
   moved only when an item it touched moved.
1a. **The self-update continue step** (`self-update.sh:372-395`) goes off with P0. It was built so that work goes
   on after an update; under «no session continues itself», a session waits for a person after an update.
2. **(b)** Stops: one empty turn, two unchanged turns, a 40-step turn, the ceiling. Nothing restarts itself; a stopped item waits for a person.
3. **(c)** One meter; attribution per turn (goal rounds in his own session are self-activated); the door refuses unless the proof holds.
4. **(d)** The screen, judged on its mock.
5. **Order:** P0, P1, then A–D. Re-enabling any source is his separate request, one source at a time, after D is live.
6. **Scope:** treated here as a person's, not self-activated — the Claude-side Stop hook (`.claude/hooks/work-left.py`
   check 4 holds a session open; DeepSeek does not bill it) and the Telegram group desk, which forwards a person's
   message (`apps/telegram/relay/relay_group.py:175-176`). Does the ₪1 rule cover them?
