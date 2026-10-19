# Backend audit: can the live platform actually do what the simulation shows?

`digital-office/sim/PORT-PLAN.md` orders the UI work. This answers the question that decides whether
that plan takes weeks or months: **for every behaviour the simulation demonstrates, does a live
endpoint exist to serve it?**

Checked route by route against `apps/drive/` and `apps/mail/` as merged. Verdict first, because it
is better news than the PORT-PLAN's own phrasing suggests:

> **Nothing in the sim needs an architecture change. Two apps need new endpoints, one needs two new
> columns, and exactly one item — mail threading — is a genuine capability the platform does not
> have today and has already been bitten by.**

---

## Drive

The PORT-PLAN's C11 line reads: *"Backend: `view=recent|starred|shared`, `POST api/star`,
`GET api/storage`, and an `opened` column (Recent sorts by last-opened, NOT created)."*

All four are absent. `GET /api/files` today accepts only `folder` and `trash`:

```python
return jsonify({"files": ad.files(request.args.get("folder", ""),
                                  request.args.get("trash") == "1")})
```

| Need | Status | Cost | Why that cost |
|---|---|---|---|
| `opened` column | missing | **low** | `drive_files` is a real Postgres table with `ensure_schema()` + `_migrate_column_types()` already doing additive migrations. One `ADD COLUMN IF NOT EXISTS opened timestamptz`, stamped on `content()`. |
| `starred` | missing | **low** | Same table, same migration. `POST /api/star` is a two-line route over it. |
| `view=recent\|starred\|shared` | missing | **low** | `files()` already builds its WHERE clause; `view` selects the predicate and the ORDER BY. `recent` = `ORDER BY opened DESC NULLS LAST` — which is the whole point of the column. |
| `GET /api/storage` | missing | **low–medium** | `SUM(size)` over the table is trivial; a real *quota* needs the storage backend's number. Supabase storage does not expose one per-bucket, so this reports usage and a configured ceiling. |
| `shared` | missing | **medium** | The local adapter has no sharing model at all. See "the honest gap" below. |

**The Google adapter is nearly free.** It already fetches `fields='*'` — the complete Drive
resource — so `starred` and `viewedByMeTime` are *already in the response* and are simply dropped by
`_row()`. For that backend this is a mapping change, not a feature.

**The honest gap: `shared`.** Google Drive has a first-class sharing model; the local adapter has
none, and `drive_files` has no owner or ACL column. Options, in order of preference:

1. **Report it empty on local, populated on Google.** The view exists, the app degrades honestly.
2. Add a minimal `shared_with text[]` and a share endpoint — real work, and it invents a
   permissions model the platform does not otherwise have.

Option 1 is the right first move. The sim can show a populated Shared view because it has fixtures;
a local deployment with no sharing concept showing an empty Shared view is *correct*, not a defect —
but it means **panel equality for that one panel will not hold on a local backend**, and the plan
should say so rather than have someone chase it.

---

## Mail

The PORT-PLAN's C12 line reads: *"Backend: persist starred/important/snoozed/archived, honour
`view=`, `POST api/mark`, `GET api/thread/<id>`."*

The mail service (`apps/mail/mailapi/service.py`, :8970) is a **label-oriented IMAP executor**:

```
/search  /message/<uid>  /labels  /labels/add  /labels/remove
/labels/create  /labels/delete  /append  /send
```

That shape is the key to the estimate. In Gmail's model, starred / important / archived **are
labels** — so most of this row is a thin translation over endpoints that already exist and are
already exercised by every INDOX sync suite.

| Need | Status | Cost | Why that cost |
|---|---|---|---|
| starred, important, archived | **effectively present** | **low** | `labels/add` + `labels/remove` with `STARRED` / `IMPORTANT` / removing `INBOX`. Already how the label engine works. |
| `POST api/mark` | missing as a name | **low** | An alias over `labels/add`+`labels/remove` so the UI states one intent instead of composing two calls. Worth adding for the UI's sake, not the backend's. |
| `view=` | missing | **low** | `search` takes a Gmail-syntax query and `_query_to_criteria` already translates `label:`/`-label:`/`is:unread`. `view=starred` becomes `label:STARRED`. |
| whole-mailbox counts | **partly present** | **low** | local `search` already returns `count`, `total`, `has_more`, `next_cursor`. Gmail backend needs the same fields. |
| **snoozed** | missing | **medium** | Not a Gmail label and not an IMAP concept: it needs a due-time per message and something to un-snooze it. That is state the mail service does not keep and a scheduler it does not have. |
| **`GET api/thread/<id>`** | **missing — real gap** | **medium** | See below. |

### Threading is the one real capability gap, and it is already causing damage

The mail service has no thread fetch. This is not a new discovery — it is written into
`ai/context/mail-organizer-refactor.md` as a live bug:

> `Get Gmail Thread` is **disabled**… so `thread` is empty for every message, and rule 10
> (`BS_TO_SYNC`) reads `thread.messages[0].text` — it cannot match. Same for
> `CORRESPONDENCE_STARTED` and `BS_REPORT_REQUEST`.

So **three label rules are dead right now** for want of the same endpoint the sim's conversation
view needs. IMAP can do it: `X-GM-THRID` is already how the service maps ids, and the summary
already carries `gm_thrid`. Implementing `GET /thread/<id>` therefore fixes the sim port **and**
three broken rules with one change — which makes it the highest-value backend item on the list, and
it should move ahead of the UI work rather than waiting for Phase 3.

---

## INDOX

Phase 4 (C8 instances, C9/C10 the sync surface) is the largest UI change but the **smallest backend
question**: `INDOX-SYNC-PORT.md` carries the full contract, `incoming_documents` and `sync_registry`
are real tables, and the instance model is a scoping concern over queries the app already makes.
Nothing here needs a new capability. It needs care, not invention.

Two things worth flagging before that phase starts:

- **`sync_registry` is untouched by design** — the mail-organizer refactor decision records it as
  indox-owned and a separate task. C8's per-instance registry must not quietly reopen that.
- **Kafka is gone** (removed earlier; the trigger is 30s DB polling). C8's changelog entry says
  "drop Kafka" — already true here, so that sub-item is a no-op rather than work.

---

## What this means for the plan

The PORT-PLAN's ordering is sound but its Phase 3 hides the only genuinely risky item inside a UI
phase. One change to the order:

**Do `GET /thread/<id>` first, in Phase 1.** It is backend-only, independently testable, unblocks
mail's conversation view *and* repairs three dead label rules, and it is the one item where "add a
column / add an alias" does not describe the work.

Everything else on the backend side is additive and low-risk: two columns, four thin endpoints, and
a mapping change on the Google adapter that surfaces data already being fetched.

The single item that cannot be fully satisfied is Drive's **Shared** view on a local backend, and
the right answer there is to let it be honestly empty rather than invent a permissions model to
make one panel match.
