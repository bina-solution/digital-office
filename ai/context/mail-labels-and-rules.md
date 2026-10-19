> **SUPERSEDED 2026-09-03 (owner Decision N1):** there is ONE rules store — the mail app's organizer settings (`/organizer/settings`), edited in the mail console. `indox_<tenant>.tag_rules` is retired (renamed `tag_rules_retired_20260903`); §2–§3 below describe the split that no longer exists. Current design: `apps/indox/RELEASE-DECISIONS.md` and `apps/indox/indox solution.md`.

# Mail labels and rules — the full map (labels registry, per-profile scoping, and the two things everyone calls "label engine")

**Status:** current as of the per-profile label registry fix (this doc). Read this before touching
any label/rule surface in `apps/mail` or `apps/indox` — the biggest risk in this area is conflating
two systems that share a name by accident.

## 0. The one-sentence answer

There are **two unrelated systems** that both get called "the label engine" in conversation. **(A)**
mail's own local-mode label registry is now scoped **per mail profile**. **(B)** INDOX's Gmail
document-classifier workflow (renamed **Mail Label Engine**, now `apps/mail/blueprint/n8n/mailLabelEngine01.json`
— moved from indox per `mail-organizer-refactor.md` 2026-08-05; was `qdWiksr1FDofpDmh.json` / "Gmail Label Engine")
is a **separate, mail-owned system consumed by INDOX**, scoped by
INDOX **instance**, not by mail profile. **They must never be conflated.** §3 below states the
boundary explicitly.

---

## 1. (A) The LOCAL label registry — now per profile

### What it is

The mail service (`apps/mail/mailapi`) is a protocol-agnostic abstraction over three backends
(`adapters.py`): `LocalBackend` (our own Postfix/Dovecot), `GmailBackend` (app password),
`GmailOAuthBackend`. Gmail keeps labels itself — nothing to do there. **Only the local backend**
needs a label registry, because IMAP has no concept of a human-readable label: Hebrew/space names
aren't valid IMAP keyword atoms, so every label name is mapped to a deterministic short atom
(`kw<base32>` or a blake2s hash when the base32 form is too long — `local_app.py:145-169`), and that
name↔atom mapping has to be persisted somewhere so `/labels` can decode atoms back to names.

### Where it lives now

`apps/mail/mailapi/local_app.py:96-121` (module docstring + `LABEL_REGISTRY_DIR`):

```
LABEL_REGISTRY_DIR = os.environ.get("LABEL_REGISTRY_DIR", "/data/labels")
_reg_path_for(connection_id)  ->  /data/labels/<connection_id>.json
```

Every `LocalBackend` instance is one profile's mailbox (`local_app.py:438-475`, the class docstring:
"one PROFILE on the private mail engine"). `adapters._build` now passes the resolved `connection_id`
into the constructor (`adapters.py:257-259`), and `LocalBackend.__init__` stores it and computes
`self.reg_path` once (`local_app.py:465-471`). Every function that used to read/write the single
shared `/data/labels.json` (`_load_reg`, `_save_reg`, `_reg_label`, `_decode_atoms`, `_resolve_atoms`,
`_query_to_criteria`/`_term`, `_summary`) now takes `reg_path` as an explicit parameter, and every
`LocalBackend` method call site passes `self.reg_path` (`local_app.py:727-1080`).

**Before this fix:** `REG_PATH` was a single module-level constant (`/data/labels.json`, one file per
*container*, not per mailbox). Two profiles' worth of messages/folders/flags were already correctly
isolated — those live in genuinely separate dovecot mailboxes — but the atom↔name *translation
table* was shared, so `GET /labels` returned the same ~35 names for `admin` and `user2` regardless of
which mailbox was actually selected, and a label one profile created was visible (as a raw atom
string, if the other profile happened to apply the same keyword) to a mailbox that never touched it.

**No migration from the old shared file**, per explicit instruction: a fresh per-profile file is the
clean answer, and a brand-new profile must not inherit another profile's label vocabulary. The old
`/data/labels.json` is simply no longer read; nothing deletes it, nothing reads it either.

### Every route that touches it (all already threaded `connection_id`, confirmed, not changed)

`apps/mail/mailapi/service.py:187-246` — `POST /labels/add`, `POST /labels/remove`, `GET /labels`,
`POST /labels/create`, `POST /labels/delete`, `POST /labels/rebuild` (local-only, 501 on Gmail). Every
one resolves its backend via `_backend(connection_id)` (body field for POST, query param for GET),
which is `adapters.resolve_active(connection_id)` — the single choke point (`adapters.py:282-317`).
`/message`, `/thread`, `/search` also decode labels through the same per-connection registry (they
return a message's `labels` field).

### Proof (real output, local WSL stack, `bbox run`)

Two declared profiles, `admin` (`mail_imap_local-4712e62a`) and `user2` (`mail_imap_local-91d13796`):

```
create as admin:      POST /labels/create {"name":"admin-only-label","connection_id":"...4712e62a"}
                       -> {"name": "admin-only-label", "ok": true}
admin /labels:         {"labels": ["admin-only-label", "DRAFT", ... "UNREAD"]}
user2 /labels:         {"labels": ["DRAFT", ... "UNREAD"]}                       # admin-only-label ABSENT

create as user2:       POST /labels/create {"name":"user2-only-label","connection_id":"...91d13796"}
user2 /labels:         {"labels": ["user2-only-label", "DRAFT", ... "UNREAD"]}
admin /labels:         {"labels": ["admin-only-label", "DRAFT", ... "UNREAD"]}   # unchanged, user2-only-label ABSENT

brand-new profile (never had any file written): _load_reg() -> {}   # empty, no inherited names
```

Isolation holds both directions; a brand-new profile starts empty (no ~35 inherited names).

### Reachable through the real mail UI — traced, not clicked (no Playwright)

Neither mail UI passes `connection_id` on label calls at all:

- `apps/mail/mailapi/static/app.js:1214` — `jsoft("labels")`, `jf("labels/create", post({name:n}))`,
  `jf("labels/add"|"labels/remove", post({uid, labels}))`. No `connection_id` anywhere in this file.
- `apps/mail/mailview/app.py:59-61` — `GET /api/labels` → `gi("/labels")`, no `connection_id`.
  `apps/mail/mailview/static/app.js:314` — `jf("api/labels")`. Same story.

Both UIs rely entirely on mailapi's **active connection pointer** (`/data/active.json`,
`connections_client.py`). The switcher that changes it is `POST /connections/select` — the
console's connection bar, per `app-engine-pattern.md` §8 slot 5. This is by design, not a gap: it is
the exact same mechanism every other per-profile surface in mail already uses (messages, folders,
flags all follow the active pointer the same way).

**Proved via the same calls the UI itself makes** (`POST /connections/select` then a plain,
no-override `GET /labels` / `GET /api/labels`):

```
POST /connections/select {"id":"mail_imap_local-4712e62a"}  -> {"active":"...4712e62a","ok":true}
GET  /labels (no override)                                  -> admin's set (admin-only-label present)
POST /connections/select {"id":"mail_imap_local-91d13796"}  -> {"active":"...91d13796","ok":true}
GET  /labels (no override)                                  -> user2's set (user2-only-label present)
mailview's own GET /api/labels (through its own container)  -> reflects whichever is currently active
```

This **is** click-verification's functional equivalent: it is the identical HTTP call sequence a
person switching the connection bar and reloading the mail UI would produce. No UI framework was
driven, so this is stated plainly as the limit of what was proved without Playwright.

### Remaining gap in (A) — stated plainly

The **scheduled/manual** label-engine paths (§2 below) still do not pass `connection_id` when calling
mail's message/label ops — they always act on whichever connection is currently active. Only the
`Sub Trigger` → `Sub Search` on-demand path threads `connection_id` end to end (see §2). This was
already true before this fix and is unchanged by it; it is a property of workflow (B)/(C), not of
the registry.

---

## 2. (C) — what actually shipped for "manage labels in the mail UI"

Investigated: `apps/mail/mailapi/static/app.js` (full read), `apps/mail/mailview/static/app.js` (full
read), `git log --all --grep=organizer`, `ai/context/mail-organizer-refactor.md`.

**Verdict: plain label CRUD, not a condition-based rule engine.** Both mail UIs let a person create,
rename (via delete+recreate — there is no rename op), and delete labels, and assign the two
`FLAG_LABELS`-style system mappings (STARRED/IMPORTANT) by starring/flagging a message. There is no
"if sender contains X, apply label Y" screen anywhere in mail. The one place such a screen was ever
*planned* is `ai/context/mail-organizer-refactor.md` ("Organizer settings UI in mailview" — step 7 of
an explicitly **"planned, not started"** 9-step plan). It was never built. Confirmed by: no
`organizer` symbol in either app.js, no route in `service.py`/`mailview/app.py` for rules CRUD, and
the plan doc's own status line.

**Consequence:** scoping the label registry per profile (§1) is the *entire* fix this task's "make
sure the label engine is per-profile" ask required for the mail UI. There is no rule-storage to scope
per profile because no rule storage owned by mail exists yet.

---

## 3. (B) — INDOX's document classifier, now "Mail Label Engine" — separate system, do not conflate

**This is emphatically not the same system as §1 or §2.** It is INDOX's Gmail-sourced document
classifier, and it was, until this task, hard-coupled to Gmail and to INDOX's own rule table.

### What it is

`apps/mail/blueprint/n8n/mailLabelEngine01.json` (id `mailLabelEngine01`, renamed from
`qdWiksr1FDofpDmh` / display name "Gmail Label Engine" → **"Mail Label Engine"**). It reads
`public.tag_rules` (`apps/indox/blueprint/fixtures/schema.sql:310-331,359-381`) — rows of
`{TYPE, LABEL, RULE, KEY, EVENT}`, scoped by an **INDOX instance** column
(`instance TEXT not null default 'incoming-documents-main'`), **not by mail profile**. Its
`Lable Engine` code node evaluates each rule's JS expression against `email`/`thread`/`attachments`
objects built from a fetched message, and applies/removes labels through mail's own HTTP API so that
INDOX's sync pipeline (`syncV3*`, keyed on `label:<TO_SYNC name>`) can find labelled mail.

### The rename and de-Gmail-ification done in this task

1. **Renamed**: workflow `name` "Gmail Label Engine" → "Mail Label Engine"; workflow `id`
   `qdWiksr1FDofpDmh` → `mailLabelEngine01` (readable id, matching this repo's convention —
   `gmailApiRouter01`, `mailApi01`, `syncV3Unit0001`, `indoxSetupWF001`); **file renamed to match**
   (`qdWiksr1FDofpDmh.json` → `mailLabelEngine01.json`), same convention every other blueprint file
   in this repo already follows (filename == workflow id).
2. **Every reference to the old id/name updated** across the repo: `apps/indox/blueprint/n8n/mailOrgTest00001.json`
   (the E2E test harness's `LE Engine`/`SL Engine` executeWorkflow nodes), `apps/mail/mailapi/{adapters,app,service}.py`,
   `apps/mail/mailview/app.py`, `apps/indox/hooks/test.py`, `scripts/n8n-exec-dump.py`,
   `scripts/refactor/workflow-input-lint.py`, `scripts/_inspect_le.py`, `scripts/_le_addcheck.py`,
   `scripts/_le_outcome.py`, `scripts/_run_label_engine_test.py`, and the live current-state docs in
   `ai/context/` (`mail-organizer-refactor.md`, `architecture-map.md`, `api-abstraction-refactor.md`,
   `incoming-documents-architecture-and-productization.md`, `indox-full-ioc-outline.md`,
   `incoming-documents-onboarding.md`, `gdrive-sync-pairs-refactor.md`) and
   `ai/obsidian/Projects/deployment-hacohen/n8n System Map.md`.
   **Deliberately left untouched:** `next-7h/*.md` (dated point-in-time snapshots, e.g.
   `GOOGLE-API-AUDIT.md` is a 2026-06-21 audit — editing them would misrepresent history, the same
   reason git log/commit messages aren't rewritten); `ci-artifacts/n8n-blueprint-map.md` and
   `ci-artifacts/n8n-node-coverage.json` (CI-generated artifacts that self-correct on the next
   coverage run against the live, renamed workflow); anything under `legacy/`, `attic/`, `data/`
   (backups/archives), and `.claude/worktrees/*` (another session's isolated worktree).
3. **Removed the native Gmail nodes.** The workflow had exactly two: `Gmail Trigger`
   (`n8n-nodes-base.gmailTrigger`) and `Get Gmail Thread` (`n8n-nodes-base.gmail`) — **both were
   already `disabled: true`** (confirmed by reading every node's `disabled` flag before touching
   anything). `Gmail Trigger` fed nothing else the live paths depend on (Schedule Trigger, the manual
   trigger, and `Sub Trigger` are the real entry points) — deleted outright.
   `Get Gmail Thread` was a genuine dead end whose absence is a **documented live bug**
   (`ai/context/mail-organizer-refactor.md` §"two live bugs": `BS_TO_SYNC`, `CORRESPONDENCE_STARTED`,
   `BS_REPORT_REQUEST` read `thread.messages[0].text` / `thread.from` against a thread that was always
   empty). It is **replaced, not just deleted**, with a live `executeWorkflow` node of the **same
   name** (so the `Lable Engine` code's `$("Get Gmail Thread")` reference needs no change) calling
   `gmailApiRouter01` with `op: "getThread"` — the exact op `service.py`'s `GET /thread/<tid>` route
   already implements (`adapters.CANONICAL_OPS["getThread"] = "thread"`). `gmailApiImap01.json` (the
   op router) gained the missing branch: a new `Op Switch` rule, `http:getThread` (GET
   `/thread/<id>?connection_id=...`), and a `shape:getThread` code node that adds Gmail-cased aliases
   (`From`/`Subject`/`text`/`textPlain`/`html`/`textHtml`) alongside mailapi's own field names —
   additive only, so nothing that already reads the lowercase fields breaks — which is what makes the
   three previously-dead rules able to match real content instead of nothing.
4. **Every remaining call in the workflow already went through mailapi, not Gmail directly** — this
   was true *before* this task (`Get many messages`, `Get a message`, `Add label to message`,
   `Remove label from message`, `Create a label`, `Get many labels`, `Get final labels`, `Sub Search`
   all call `gmailApiRouter01` → `gmailApiImap01` → `http://mailapi:8970`, verified by reading every
   `executeWorkflow` node's `workflowId`/`params`). **Gmail still works, through mailapi**: whichever
   backend `connection_id` resolves to (`LocalBackend`, `GmailBackend`, `GmailOAuthBackend`) is a
   server-side decision in `adapters.resolve_active` — the n8n workflow has zero branching on
   protocol anywhere. `Sub Search`'s params were fixed to actually forward `connection_id`
   (`local_app.py`/`gmailApiRouter01` already accepted it as an input on `Sub Trigger`, but the call
   silently dropped it before this fix — a real, if narrow, existing bug, caught because
   `mailOrgTest00001.json`'s `LE Engine`/`SL Engine` nodes already try to pass one).

### What was proved

- Repo-wide grep for the old id, outside legacy/backup/worktree/CI-artifact paths: **zero
  matches** (`grep -rl qdWiksr1FDofpDmh` across `.py/.json/.md/.sh/.yaml`).
- The renamed workflow JSON contains **zero** `n8n-nodes-base.gmail`/`gmailTrigger` node types, zero
  hardcoded Gmail hosts (`imap.gmail.com`, `gmail.googleapis.com`).
- Pushed to the local WSL stack's n8n (`bbox n8n push`) and verified live: `n8n list:workflow` shows
  `mailLabelEngine01|Mail Label Engine`, activated. The **orphaned old row** that upsert-by-id
  necessarily leaves behind (`qdWiksr1FDofpDmh`/"Gmail Label Engine" — renaming the `id` field creates
  a *new* DB row rather than renaming in place) was **archived and deleted** via n8n's documented REST
  lifecycle (`POST /rest/workflows/<id>/archive` then `DELETE /rest/workflows/<id>` — this is on the
  **local WSL dev sandbox only**, never production) so the deployment does not end up running two
  active copies of the same 15-minute schedule. Confirmed: only `mailLabelEngine01` remains.
- **Not proved**: triggering against a real Gmail connection. This local deployment has exactly two
  connection instances, both `mail_imap_local` (`admin`, `user2`) — no Gmail app-password or OAuth
  instance exists here to trigger against. The architectural claim (identical mailapi calls, differing
  only in `connection_id`) rests on code inspection of `gmailApiImap01.json`'s `http:*` nodes, which
  take `connection_id` as a plain string parameter with no protocol branching — not on a live Gmail
  run. State this plainly rather than fabricate a Gmail trigger.

**A real regression was caught and fixed during this verification, not just claimed fixed.** The
first `bbox indox test mail_organizer` run after the rewrite failed: `died at node 'LE Engine':
Cannot read properties of undefined (reading 'json')`. `scripts/n8n-exec-dump.py` traced it to the
new `Get Gmail Thread` node returning **0 items** instead of thread data — and one level up,
`gmailApiRouter01`'s own `When Called` node had received `{"op": null, "params": null}`. This is
byte-for-byte the bug commit `bbbb0a7b` documented and fixed once already ("one stale typeVersion
made the whole mail organiser a no-op" — an `executeWorkflow` node on `typeVersion 1.1` sends `null`
for every field when any one of them is a literal rather than an expression). My replacement node had
been authored at `1.1` (matching an *older*, unrelated historical note about avoiding "Workflow does
not exist"); every other `executeWorkflow` node in this same file is `1.2`. Bumped `Get Gmail Thread`
to `1.2` to match, repushed, reran: `mail_organizer` now passes **2/2** (label-engine 8/8,
system-labels 3/3), and `Get Gmail Thread`'s own execution data now shows a real thread (`from`,
`subject`, `messages[]` with real `body_text`) instead of nothing — meaning `BS_TO_SYNC` /
`CORRESPONDENCE_STARTED` / `BS_REPORT_REQUEST` (documented dead since `Get Gmail Thread` was
disabled) now see real content to evaluate against, for the first time. This is exactly the failure
mode the repo's own history warns is invisible in review — worth recording so a future reader trusts
the "2/2 PASS" line because of how it was reached, not just because it is asserted here.

### What was deliberately NOT done, and why — the rule-source relocation

The workflow's `TGET Tag Rules` / `Call Tag Rules` nodes still read `tag_rules` via `indoxApiRouter01`
(hardcoded `instance='incoming-documents-main'`, `local_app.py`-adjacent comment: "part of the
v1/demo/test tail the plan scopes separately"). A later instruction asked for the rule *source* to
also move out of INDOX entirely, into wherever mail's own label-engine rules end up living. **This was
not done.** Reasoning, stated plainly:

- (C) established there is **no mail-owned rule store to move rules into** — it was never built (see
  §2). Doing this properly means building it first: `ai/context/mail-organizer-refactor.md` already
  specifies the design (an `options` bag on connection instances — deliberately **not** a new
  Supabase table, to avoid adding a `sql` dependency to `mail`) as its own **ordered 9-step plan**,
  whose step 0 is explicitly "build the gate first... without this every later step is unverified."
- The one gate that exists today (`mail_organizer` suite, `mailOrgTest00001.json`, currently
  **passing 8/8 label-engine + 3/3 system-labels**) asserts against `tag_rules`-seeded rules. Moving
  the rule source without rebuilding that gate against the new source would mean shipping a change to
  a **live production document-intake pipeline** with no test proving it still classifies mail
  correctly — exactly the failure mode this repo's own history warns about repeatedly (a stale
  `typeVersion` silently made the whole engine a no-op for an unknown period; `bbox baseline` stayed
  green through a completely broken label engine because nothing exercised labelling).
- This is squarely what AGENTS.md means by "this is production... when in doubt, do nothing and
  report": the rename + Gmail-native-node removal are mechanical, verifiable, and low-risk; migrating
  a production classifier's rule storage ownership is a multi-step project the repo's own docs already
  scope separately, and rushing it inside this task risks silently breaking INDOX document ingestion
  with no gate to catch it.
- **This is the one item from the brief left undone.** It is flagged here, not hidden in prose:
  `mailLabelEngine01.json` still reads `tag_rules` (grep count: 1 reference, `Call Tag Rules` node)
  from INDOX, scoped by INDOX instance, exactly as before. It does **not** read or write anything
  keyed by mail profile/connection_id. The dependency is real and is now stated explicitly so a future
  session doesn't have to re-derive it.

---

## 4. End-to-end request flow: "an operator switches profile in the mail UI"

1. Console's connection bar (or `mailapi`'s own served UI) issues `POST /connections/select {id}` —
   `connections_api.py` (route confirmed: `@bp.post("/connections/select")`).
2. This writes the new active id to `/data/active.json` (`connections_client.py`), the app-local
   pointer — never routed through the connections vault itself, so a vault outage degrades a *list*,
   never the current selection (`profiles-and-engines.md` §"do not build").
3. Every subsequent op call with **no** explicit `connection_id` (which is every call both mail UIs
   make — §1) resolves via `adapters.resolve_active(None)` → falls back to `cc.active()` → builds
   (or reuses, from `_backends` cache keyed on `(cid, credential fingerprint)`) a `LocalBackend` for
   that profile's mailbox, now carrying `self.reg_path = /data/labels/<cid>.json`.
4. `/labels`, `/message`, `/thread`, `/search` all decode label atoms through **that** file. Switching
   the connection therefore switches which profile's label vocabulary every surface shows — no
   per-call `connection_id` needed anywhere in the UI layer, because the active pointer already is the
   per-profile choke point.
5. Creating/deleting a label (`/labels/create`, `/labels/delete`) writes to the same `self.reg_path`,
   so it is durable across restarts and correctly invisible to every other profile.

## 5. Gaps found and not fixed (stated plainly, not buried)

1. **(B)'s rule source is still INDOX's `tag_rules`, not mail's** — see §3's "deliberately NOT done."
2. **(B)'s scheduled/manual scan paths still don't carry `connection_id`** — only `Sub Trigger` →
   `Sub Search` does (fixed in this task). The 15-minute `Schedule Trigger` path always acts on
   whichever connection is currently active; making it scan every declared mail profile (or a
   configured subset) is a design decision nobody has made yet, not a bug this task's scope covers.
3. **(C) has no rename op for a label** — only create + delete. Not required by this task, noted for
   completeness since it came up while reading the UI code.
4. Click-verification of the mail UI's connection switcher was done via the identical API calls the
   UI itself makes, not via a driven browser (no Playwright, per instruction) — see §1's proof section
   for exactly what was and wasn't demonstrated.
