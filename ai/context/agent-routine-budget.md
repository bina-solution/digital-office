# «עזריה שגרה» — תשומת לב מנוהלת: מסלולים, תקציב לכל פריט, וכל עבודה משוקפת בעלותה

The owner, 2026-10-13, after the night that cost $4.92:

> «בעצם הדרך האידיאלית לפתור את זה עי ניהול הגבלה של תשומת לב לכל משימה … כל דבר שעזריה עושה אמור
> להיות קשור למשימה קיימת וכל משימה דבר ראשון מקבלת תקציב … וגם כל משימה נוסף סימון שמסמן כמה היא
> עלתה בטוקנים ובמטבע»
> «תחשוב ממש לעומק תביא פיתרון מלא אני גם לא רוצה שיצתברו אלף שיחות אז תיצור אותם תחת תיקייה „עזריה
> שגרה” והכל משוקף כולל העלות ושום דבר לא רץ קבוע אם משימה ברורה מאושרת עם תקציב קיים»

This file is the model. The incident it answers:
`issues/an-untended-goal-loop-has-no-ceiling-and-a-pause-does-not-hold-2026-10-13.yaml` (critical).

## The one rule

**Nothing runs unattended unless an approved work item with a remaining budget exists.**
Not "an active goal", not "a session that exists" — an *item*, *approved by a person*, with a
*ceiling that has not been reached*. Everything else in this document is the machinery of that
sentence.

## 1. The four nouns

| noun | what it is | who owns it |
|---|---|---|
| **פריט (item)** | the unit of work, on the hub (DGO). It carries the budget and the approval | the owner (approval, budget), the agent (the work) |
| **מסלול (lane)** | a named, long-lived line of work — `שגרה`, `בדיקות`, `לילה`. A lane is **not** one session per item | the office (a fixed, small number) |
| **שיחה (session)** | a lane's current session. It is created *inside the «עזריה שגרה» workspace*, works ONE item at a time, and is **recycled** (hand-off + archive) when the item closes or the lane crosses its context ceiling | the office |
| **תוכנית (plan)** | a set of items with a plan-level budget (a weekend, a week) | the owner |

A lane is the answer to "אלף שיחות": the number of **active** sessions is the number of lanes (2–3),
and finished ones are archived into the workspace, which is history rather than sprawl.

## 2. The workspace «עזריה שגרה» — how a folder becomes one

The harness has a workspace registry (`@deepseek-ai/dsh-workspace`), and the office already registers
one through its own plugin:

```
apps/bina-ds/plugins/office-workspace/lib/index.js
    ctx.workspaceRegistry.create(path, title)      # «הלשכה הדיגיטלית» → /root/deployment-hacohen
```

So the routine is not a folder that has to be invented: it is a **second registered workspace** —

* directory: `/data/dsh/routine` (inside `bina_ds_home`, so it is backed up with the agent's volume);
* title: **«עזריה שגרה»**;
* the sidebar groups sessions by workspace, so the routine's sessions live under that heading and
  never mix into the office conversation list.

The plugin gains one entry (`workspaces: [{path, title}]`), and the ledger (below) lives beside it.
Registering it is a `workspaceRegistry.create` call — for a directory that already has a record it is
a no-op, so the plugin stays idempotent at every boot.

## 3. Budget and approval — where they are written

Both live **on the item**, in the hub plan, so they are declarative and visible to every reader:

```yaml
  - key: ui2-060
    labels: [ממשק, מאושר]           # ← the owner approved it
    description: |
      מה נדרש: …
      תקציב: 5                      # ← ₪ (or תקציב: ללא הגבלה)
```

* **`מאושר`** — a label only a person adds. The agent never approves its own item, and never raises a
  budget: raising a ceiling is the owner's decision by construction, not by policy.
* **`תקציב:`** — one machine-readable line in the description. No new Plane schema, no new field, and
  a reader that does not know the convention simply sees a sentence.

## 4. The gate — what makes the rule real

The pulse (`apps/bina-ds/pulse.sh`, every 300 s, holding the agent's own token) is the **only**
automatic driver. It becomes a gate instead of a pacer. For each session that holds a goal:

1. resolve the **item ref** from the goal's objective (the goals already name it: `bbox agent do DGO-…`);
2. read the item — approved? budget? spent so far? (from the hub's cache, below);
3. price this session's own usage — `GET /v1/sessions/<id>` → `.tokens`, multiplied by the office's
   own price book (`plugins/cost-meter/lib/pricing.js`, peak/off-peak by the sample's own timestamp);
4. decide:
   * **eligible** → re-arm and continue, and add the delta to the ledger;
   * **not approved / no budget / exhausted** → **do not re-arm**, notify (`error`, with the exact
     reason and the numbers), and clear the goal so nothing resurrects it.

Two things this kills, both measured on 2026-10-13: a `complete` goal re-created with a fresh
400-round cap (9× that day), and a `pause` that the watchdog undid within five minutes.

### Fail closed, not open

The hub can be unreadable (it was, all day: `plane_local_api_token-local` → HTTP 404, the hub runs on
another office and needs `./bbox project-pln onboard`). Therefore:

* every successful hub read **writes a cache** (`/data/dsh/routine/hub-cache.json`, with its timestamp);
* a **stale or missing cache means no new work starts** — the gate refuses, and the notification says
  "the hub is not readable, so nothing is approved" rather than silently continuing;
* a running lane is not killed by a hub outage; it simply gets no *new* rounds.

## 5. Recycling a lane, instead of a 792k-token marathon

Measured on 2026-10-13: one session sent **792,751 tokens** in a single request, re-sending the whole
conversation on every step; 830.9M of the day's 832.9M tokens were those cache reads. The fix is not a
smaller cap, it is a shorter life:

* a lane's session hands off when the item closes **or** the session's context passes its ceiling
  (`routine.yaml → contextCeiling`, default 250k tokens);
* the hand-off is mechanical: the outgoing session writes a short **hand-off summary** into the item
  (what was done, what is left, what was measured) and the pulse opens the **next session in the same
  lane** with that summary as its first message;
* the old session is archived. Nothing accumulates but the ledger and the item's own history.

## 6. Everything reflects its cost

| level | what it shows | where |
|---|---|---|
| session | the conversation's price (already shipped) | the composer pill (`cost-meter`) |
| lane | ₪ + tokens for today, and *why it is stopped* if it is | the «עזריה שגרה» view |
| **item** | ₪ + tokens against its budget, and the ETA at the current pace | the item's marker (hub and console) |
| plan | the sum over its items against the plan budget | the plan's header |
| folder | the day's and the week's total across all lanes | the workspace heading |

Numbers are always the same two inputs — the session's own `.tokens` and `pricing.js` — so the meter,
the timeline, the item marker and the folder total cannot disagree.

## 7. Peak hours — half the price for the same work

DeepSeek's published book: peak is 01:00–04:00 and 06:00–10:00 UTC (= 04:00–07:00 and 09:00–13:00 in
Israel), off-peak is exactly half. Measured on 2026-10-13: 363.9M of the day's cache-hit tokens were
billed at peak — the hours the office happens to work in. The gate therefore holds *new* rounds from
long-running lanes during peak when the item's budget is small, and prefers the night for a big plan.

## 8. Acceptance — what proves this works

1. **No item, no round.** A session whose goal names no item ref gets no re-arm, ever.
2. **No approval, no round.** An item without `מאושר` is never started by the pulse.
3. **No budget, no round.** An item without a budget line is never started.
4. **Ceiling holds.** An item at its budget stops within one tick, with an `error` notification naming
   the item, the spend and the ceiling — and does not come back.
5. **`complete` is final.** A finished goal is never re-created with a fresh cap.
6. **A night is cheaper.** The same night's work, re-run under the gate, costs less (target: $1 for
   the work that cost $4.92) with the same green gates.
7. **The ledger is the truth.** For any item, ₪ and tokens in the ledger match the sum over its
   sessions' own usage, priced by `pricing.js`.
8. **The folder is a folder.** The sidebar shows «עזריה שגרה» with its lanes, and the active session
   count never exceeds the number of lanes.

## Where the change lands (files)

| file | change |
|---|---|
| `apps/bina-ds/plugins/office-workspace/lib/index.js` | register the second workspace «עזריה שגרה» → `/data/dsh/routine` (config-driven, idempotent) |
| `apps/bina-ds/harness/profile/cordis.patch.yml` | the plugin's `workspaces:` list (path + title) |
| `apps/bina-ds/pulse.sh` | the gate: item ref → approval + budget → priced usage → re-arm or stop; ledger write; hand-off at the context ceiling |
| `apps/bina-ds/routine.yaml` | the lanes, the default budget per class, the context ceiling, the peak-hours policy |
| `apps/project-pln/plans/office.yaml` | `תקציב:` in each item's description, `מאושר` where the owner approved (items `agt-010`, `agt-011` are the first two) |
| the item marker | the display change proven by `ci-artifacts/task-budget-mock/` (demo) — landed in the bina/hub screens after the owner signs the mock off |

Not built yet, deliberately: nothing here rewrites the harness. The gate lives in the office's own
files, uses doors that already exist (`GET /v1/sessions/<id>`, `goal/{resume,clear}`, `messages`), and
is reversible by one line (`BINA_DS_PULSE=0`).
