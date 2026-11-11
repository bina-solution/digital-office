# goal-guard — the fence around the automatic goal round loop

One plugin, two rules, both about the harness's **goal round loop**: while a goal is active and armed,
`@deepseek-ai/dsh-goal-round-driver` gives it one more round every time its agent goes idle. That
loop is how a long objective gets carried to its end across many turns. On 2026-11-01 it also became
the most expensive thing this office has ever done.

## The incident this was written from (measured, not remembered)

`session-f7a05d7b` (titled «בדיקת אפליקציות שרצות במערכת», the DGO-553 goal):

| What | Number |
|---|---|
| rounds / steps | 961 / 2,593 |
| of those, automatic goal rounds | **935** (the owner wrote 28 messages, all in one evening) |
| goal rounds that made **zero** tool calls | **841** |
| the longest uninterrupted run of those | **398 rounds** (from turn 438) |
| rounds in the hour of 21:00 | 786 — of which **783** had one step, 0 tool calls, ~2.2 s each |
| input tokens | **1.245 billion** (99.83% cache hits) |
| average context per request | 480K tokens (median 522K, max 792K) |
| compaction in 960 rounds | **one** |
| the bill | **₪19.10** — 82% of the office's entire LLM spend for that week |
| spend when the first empty round started (20:40:51) | ₪3.60; the other ₪15.50 came after it |

And the round cap: the first goal was created with `max_goal_rounds=12`; the run then cleared it and
created fresh goals with **400** — three times, each after hitting the previous cap. A ceiling a run
can raise by re-creating the goal is not a ceiling.

Each time the run was stopped, its own closing line was, in the model's words, *"everything that is
mine on DGO-553 is implemented, deployed and proven; what is left needs your decision"*. So the loop
was spending money to re-answer a finished question.

## Rule 1 — no progress, no next round

A turn that is an automatic goal round (`user/message` whose `source.kind === 'goal'`) and that ends
without a single `tool/call` earns no next round: the goal is blocked with

```
code:    no-progress
message: סבב N הסתיים בלי אף קריאת כלי אחד … אדם מחליט אם להמשיך (resume) או לסגור
```

The driver only drives an `active` + `armed` goal, so a block is a hard stop. A round that means to
end the autonomous run has a tool for it — `update_goal complete` / `update_goal blocked` — and both
are tool calls, so neither is touched.

The check is anchored to the exact round: a stale queued round (another `goalId` or `revision`) can
never block the live goal.

## Rule 2 — the office's round ceiling

Every goal is clamped to `maxGoalRounds` (default **12**, `BINA_GOAL_MAX_ROUNDS` overrides) on
create and on edit. The model may still ask for 400; it gets the office's number. The profile also
sets the goal service's own `defaultMaxGoalRounds: 12`, so the ceiling holds even before this row
loads. Twelve rounds is not a smaller ambition — it is the run coming back to the owner, who resumes
it with one click when there is more to do.

## What it will not do

It never resumes, completes, clears or edits an objective; it never touches a terminal goal; and it
never throws on the event path (a listener that throws or blocks there disturbs every turn — the
containment rule `plugins/timeline-lanes` states). Disable with `BINA_GOAL_GUARD_DISABLED=1`, or the
profile row's `{maxGoalRounds, noProgress}`.

## Tests

```bash
node --test apps/bina-ds/plugins/goal-guard/test/*.test.mjs
```

Eleven cases over a hand-wired context (no harness needed): the empty round is blocked, the working
round is not, a human turn is not, a stale round cannot block, a terminal goal is not blocked, a
400-round goal is clamped, an in-ceiling goal is not edited, a completed goal is not edited, and both
refusals from the registry are warnings rather than throws.
