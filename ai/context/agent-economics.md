# The agent's economics — what a conversation costs, and what may spend it

**The owner's ruling, 2026-11-03**, said in his own words on a session screen showing ₪19.10:

> «זה באג קריטי של חיוב יותר בגלל פיצרים לא בשלים של עבודה אוטונומית שגם לא עשה כלום וגם בזבז מלא כסף
> סתם חייב למנוע את זה בכל דרך אפשרית ולדווח להבא לבנות רק דברים שבחיים לא מבזבזים ככה משאבים על כלום
> ושבכללי יש רק תקציב של שקל אחד ליום לדברים שמופעלים עי עצמם ותעיף את כל מה שקשור להמשך אין סופי של
> סשנים.»

This file is that ruling as a standing rule, with the measurement it came from.

## The three rules

1. **Nothing is built that can spend resources without producing a change.** A feature that spends
   tokens, money or a machine's time must be able to say, in its own output, what changed. "It might
   help" is not a change. Before a self-driving anything is turned on, the person who wrote it says
   what one of its steps produces and what happens when it produces nothing.
2. **₪1 a day is the ceiling for anything that activates itself.** A session a person opened is that
   person's business; a session a clock, a loop or a webhook opened is the office's, and it is
   budgeted per day — not per call, not per run. The grant lives at
   `data/bina-ds/sedarim/<day>/תקציב.json` (`grant`), defaults to ₪1, and a door that opens a
   self-activated session must **refuse** when the day's spend against it cannot be proven.
3. **No session continues itself.** The harness's goal round loop, the `/goal` command, the office's
   clock and every keeper that resumes a conversation are **off** (2026-11-03). Work is driven from
   the command forward, one step at a time, and what runs is what somebody can see. This is not a
   judgement on the idea of autonomous progress — it is the state until that idea has a design that
   can answer rule 1.

## The measurement behind them

`session-f7a05d7b` — «בדיקת אפליקציות שרצות במערכת», the DGO-553 goal, 2026-11-01/02:

| What | Number |
|---|---|
| rounds / steps | 961 / 2,593 |
| automatic goal rounds | 935 (the owner wrote 28 messages, all in one evening) |
| goal rounds with **zero** tool calls | **841** |
| longest uninterrupted run of them | **398** (from round 438) |
| rounds in the hour of 21:00 | 786 — 783 of them one step, no tool call, ~2.2 s each |
| input tokens | 1.245 **billion** (99.83% cache hits) |
| average context per request | 480K tokens (median 522K, max 792K) |
| compaction in 960 rounds | one |
| the bill | **₪19.10** — 82% of the office's whole LLM spend for that week |
| spend when the first empty round began (20:40:51) | ₪3.60; the other ₪15.50 came after it |

Mechanically: the round driver gave an active goal another round every time the agent went idle, and
asked nothing about what the round did; `max_goal_rounds` was raised from 12 to 400 by re-creating the
goal three times; and no component in the office counted money — the cost pill only displays it.
Prompt caching makes a token 50× cheaper, which is why a billion of them still cost ₪19 and not ₪900:
**the price was never the problem, the volume was.**

## What is in place now

- `apps/bina-ds/harness/profile/cordis.patch.yml`: `goal-round-driver` **disabled**, `command-goal`
  **disabled**, the goal service's `defaultMaxGoalRounds` at 12, and `plugins/goal-guard` mounted as
  the second fence (a goal round that ends without a single `tool/call` is blocked `no-progress`;
  every goal is clamped to 12 rounds whoever asked for what).
- `apps/bina-ds/adapter/server.mjs`: the seder door refuses a real cycle (`409 seder-budget`) while
  the day's spend cannot be measured against the grant. `{"dry_run": true}` still answers free.
- `apps/bina-ds/blueprint/n8n/binaSeder00001.workflow.ts`: the office clock is `active: false` —
  pushed to the live instance 2026-11-03.
- The office's own keepers (`pulse.sh`, `goal-keeper`) are not running and are not in this checkout;
  anything of that shape that comes back is subject to rules 1–3 first.

## Reading the money

`./bbox agent list` for sessions; the composer pill for one conversation's price (it is the
`cost-meter` plugin: DeepSeek's own published prices, peak/off-peak per request, cache buckets
priced apart). To price an old session from its own events, the same arithmetic is in
`apps/bina-ds/plugins/cost-meter/lib/pricing.js` — one implementation, three callers, no copy.
