> **CLOSED 2026-09-03:** the organizer is the one rules store; validation, rollback, a real editor (label picker, order, enable, preview) and the retirement of `tag_rules` landed with the final release (`apps/indox/RELEASE-DECISIONS.md` N1–N2). The open items listed at the end of this document are done.

# Mail Label Engine → mail app ("mail organizer")

Status: **DONE (2026-08-05).** All steps 0-8 landed: engine moved to
`apps/mail/blueprint/n8n/mailLabelEngine01.json` (id kept), rules served by mail-owned
`/organizer/*` plane on mailapi, organizer UI in mailview, indox tag_rules grid downgraded to
read-only, manifests updated (mail `mail-organizer` capability / indox `use`s it),
connection_id threaded. Gate: `bbox indox test mail_organizer`.

## Why

`Mail Label Engine` (`apps/indox/blueprint/n8n/mailLabelEngine01.json`, 54 nodes, active) is a
**mail organiser** that lives in indox only because indox depends on it: mail must carry the right
`*_TO_SYNC` label before indox will ingest it. It holds **no Google credentials** — every mail op
already goes through `mail`'s `gmailApiRouter01 → gmailApiImap01 → http://mailapi:8970`. That is what
makes the move cheap.

Only ~20 of its 54 nodes are live. Dead weight: `Main logic`/`Main logic1/2/4/5`/`Main logic BU`
(v3–v6 ancestors), the old Google-Sheets rule source (`Get Tags Settings1`, `Tag Settings1`,
`On Create Settings1`, `Split Settings2`), and the entire Redis-cache subtree (`Config`,
`If use_tag_settings_cache`, `Redis get/set` on `n8n.label-engine.settings`) — `If
use_tag_settings_cache` has no inbound edge, so nothing reaches it.

## The gate has now run, and what it says (2026-07-28)

Step 0's gate is built AND has produced its first real verdict on a from-scratch stack. Two lanes:

- **`system-labels` PASSES 3/3 (22 names).** Label creation works end to end: the engine diffs the
  rule set against `listLabels` and creates everything missing, including the 10 SYSTEM names indox
  writes but never creates. This was previously unproven.
- **`label-engine` FAILS 5/8.** On a message appended UNLABELLED with an attachment, neither
  `DOC_TO_SYNC` nor `PROCESSED` is applied — `labels=[]` — so the label-scoped sync search lists 0
  and nothing reaches `incoming_documents`.

The harness bug that hid this is fixed separately: `bootstrap_localmail()` seeds GreenMail's label
registry FROM `tag_rules`, and ran before the suites that seed `tag_rules`, so the registry was
empty. `ensure_labels_for()` now waits for the rows. With that fixed, `system-labels` went green and
`label-engine` did not — which is what makes the remaining failure a real finding rather than
harness noise.

**What the flow actually is** (traced node by node, `mailLabelEngine01.json`):

```
Schedule Trigger (15 min)
  -> Load Settings (sched)          settings.gmail.labels, built from tag_rules
  -> Get many messages              op:search, query =
                                      "-in:scheduled -label:<PROCESSED> -label:<each TO_SYNC/IN_PROGRESS>"
                                      limit 10
  -> Get a message                  op:get, params { id, attachments:false, meta:true }
  -> Start -> Batching 1 -> Start Gmail Item -> Lable Engine
```

**The attachment theory is wrong, and it is worth writing down why** so nobody spends the hour I
nearly did. `Get a message` explicitly asks for `meta: true`, which is the "names and sizes without
bytes" mode; `local_app.message()` populates `attachments` with `{filename, mimeType, size}` on
every part with a filename **regardless** of the `attachments` flag — that flag only controls
whether `data_base64` is attached. `gmailApiImap01`'s `shape:get` then builds `attachmentsMeta` from
exactly that array. So the local path does supply attachments, and `attachments.length > 0` is not
what is failing.

Also ruled out: `-label:` and `-in:` are both translated by local mode
(`_query_to_criteria` → `UNKEYWORD` / ignored), including the gmail-hyphenized spelling the engine
generates with `.replace(/ /g,'-')`.

**What is still unexplained.** The message came back with `labels=[]` — not even `PROCESSED`, which
the engine applies to to_sync mail too. Nothing applied at all is more consistent with the engine
never seeing that message than with a rule failing to match. So the next step is not more static
reading: it is one execution's data. Run the suite, then open the `Mail Label Engine` execution and
look at what `Get many messages` returned and what `Start Gmail Item` received. Two candidates worth
checking first:

- `Load Settings (sched)` builds the query from `L.PROCESSED.name` and the TO_SYNC/IN_PROGRESS
  entries. If any of those keys is missing the expression throws and the search node yields nothing.
- The suite appends mail and triggers the engine; if the append and the search race, the 10-message
  window may simply not contain it yet.

## Two live bugs found while researching (fix regardless of the refactor)

### 1. The baseline cannot see the label engine

`bbox baseline` stays **green through a completely broken label engine**. The gmail lanes in
`syncV3SourcesTest01` / `syncV3FullTest01` seed with `v3_query: 'subject:<token>'` and inject mail
that **already carries** the to_sync label (`sv3Inject3x001.json:102`). Nothing exercises labelling.

Combined with the silent-failure mode — if labelling stops, `syncV3Unit0001:194` searches, finds 0,
and reports a **healthy empty run** — gmail ingestion can die completely with every gate green.

### 2. `BS_TO_SYNC` can never fire

`Get Gmail Thread` is `disabled` (`mailLabelEngine01.json:475`), almost certainly since the
API-abstraction refactor removed Google credentials from n8n. So `thread` is empty for every
message, and rule 10 (`BS_TO_SYNC`) reads `thread.messages[0].text` — it cannot match. Same for
`CORRESPONDENCE_STARTED` and `BS_REPORT_REQUEST` (`thread.from === ...`).

Every balance-sheet document currently arrives via `DOC_TO_SYNC` or not at all. If confirmed on the
live instance, `mail` needs a `getThread` op — **not one of the 8 canonical ops**, so this is a
capability-contract change to scope deliberately.

## Operator decisions (these override the research plan)

1. **`mailview` is THE mail UI.** Not `inbox`. Only what the console already shows. The organizer
   settings screen goes in mailview. (The research recommended `inbox` on the grounds that
   `platform-service-contract.md` §5 calls mailview "an INDOX triage console" — that framing is
   superseded: mailview is the mail app's UI going forward.)

2. **Label logic and execution are fully owned by `mail`. No indox coupling.**
   indox may only **list** the tags and **select one by name** (so it can pre-configure against a
   label it knows the engine will create). The sole remaining coordination is test/demo data
   agreeing on label *names*.
   ⇒ `tag_rules` ownership moves to mail. indox's editable grid
   (`apps/indox/app/webapp/src/pages/SettingsPage.tsx:642-660`, backed by
   `_EDITABLE_CONFIG_TABLES` in `apps/indox/app/incoming_documents/api/__init__.py:1199`) becomes a
   read-only name list.

3. **`sync_registry` is untouched** — a separate task, fully owned by indox, which will implement
   connection selection there later. Do not add `connection_id` to the registry as part of this.
   > **That separate task has since shipped** (`mail-private`): registry entries now take
   > `connection_id`, threaded through `syncV3Main0001 → syncV3Unit0001 → syncV3Deliver0001`, and
   > `gmailApiImap01`'s two hand-built GET URLs (`http:get`, `http:listLabels`) carry it. Absent, every
   > op still resolves through the active pointer, so this decision held: the organizer refactor
   > still does not need to touch the registry. Step 6 below is done for the SYNC path only — the
   > label engine itself is still not connection-aware.

## Config model

Multi-connection is **already built** for credentials in `apps/mail/mailapi/`
(`connections_client.py`, `connections_api.py`, `service.py`): vault-backed instances, a provider
catalog, and `connection_id` accepted on every op (`service.py:44 _backend()`), persisted active
pointer in `/data/active.json`. The gap is only that an instance record holds `secret` and nothing
else — there is no per-connection *behaviour* store.

Add an opaque, non-secret **`options`** bag on the instance, namespaced by owning app — the Home
Assistant `data` (identity/credentials) vs `options` (tunable behaviour) split:

```jsonc
options: { "mail": { "organizer": {
  "mode": "default" | "override",
  "enabled": true, "schedule_min": 15,
  "search_extra": "-in:scheduled", "batch_limit": 10,
  "rules_ref": "tag_rules",     // when mode=default
  "rules": [ /* full row set, only when mode=override */ ]
}}}
```

**Inherit by reference, never copy at creation.** A new connection gets `mode: "default"` and no
rules of its own, so editing the default changes every non-overriding account. "Override" is an
explicit action that snapshots the current default and switches mode. Copying at creation silently
forks config, which is the failure this design exists to avoid.

The default itself is a mail-scoped singleton (`/data/organizer-defaults.json` on the
`gmail_imap_data` volume, beside `active.json` / `extensions.json`), not attached to any connection.

Rejected: `platform.state.yaml instances:` (compiler input echoed to `resolved.json`; nothing reads
it at runtime), a new Supabase table (would add a `sql` dependency to `mail`, which today uses only
`workflow` + `secrets`), Redis (the existing cache key is already dead code).

## The `to_sync` contract that must survive

`to_sync` is a **role name, not a column**. `settings.sync_registry[].labels.{to_sync,in_progress,
synced,failed}` stores **tag_rules KEYs**; `settings.gmail.labels[KEY].name` resolves KEY → label
name (searches hyphenate spaces, applies use the real name). Live: `gmail-bs → BS_TO_SYNC`,
`gmail-doc → DOC_TO_SYNC`, `gmail-link → DOC_LINK_TO_SYNC`.

Consumers that silently no-op if the map stops resolving: `SyncScanUnit0001:243,344`,
`syncV3Unit0001:194`, `syncV3Deliver0001:289,1129`, `SyncSource000001:73`, `IndoxResetGml001:128`,
`sv3Inject3x001:102`.

Two invariants the engine must keep honouring:
- **`PROCESSED` is applied to to_sync mail too** — `SyncScanUnit0001:243` deliberately does *not*
  exclude it.
- **Label creation must keep happening.** `Labels to create` diffs the rule set against
  `listLabels` and creates what's missing, including the 10 SYSTEM names indox writes but never
  creates (`IN_PROGRESS`, `SYNCED_*`, `FAILED_BS`, `SAVED_*`, `ACTION_*`, `FOUND_UNKNOWN`). On a
  fresh mailbox `addLabels` fails for a non-existent label.

## Order of work

0. **Build the missing gate first.** A lane that appends an *unlabelled* message with an
   attachment, runs the engine, and asserts the `DOC_TO_SYNC` name **and** `PROCESSED` are applied,
   then asserts `syncV3Unit0001` picks it up. Register in `apps/indox/hooks/test.py`
   (`SUITES`/`ORDER`) and `_N8N_TEST_SUITES`. Without this, every later step is unverified.
1. Prune the ~32 dead nodes in place (54 → ~22).
2. Give the engine a mail-owned rules path (today it calls `indoxSettings01` → `indoxApiRouter01`,
   a layer-2 → layer-3 inversion).
3. Add the options plane (connections `GET/PUT /api/instances/<iid>/options`, inbox
   `/connections/<cid>/options`, `/organizer/defaults`, `/organizer/effective/<cid>`).
4. `git mv` the workflow to `apps/mail/blueprint/n8n/`, **keeping the n8n id** — push upserts by id,
   so the live workflow is updated, not recreated.
5. Manifests: `mail` gains a `mail-organizer` capability; `indox` `use`s it.
6. Make the engine connection-aware (`connection_id` in params — routers pass params verbatim, so
   no router change; `http:listLabels` is the one GET needing `?connection_id=`).
7. Organizer settings UI in **mailview**; only then downgrade indox's grid to a read-only name list.
8. Clean up: drop `tag_rules` from indox's editable tables; consider moving the fixture.

⚠ **Never run `bbox n8n unpush --app indox` during this migration** — it deletes the workflow from
the live instance. `push` is upsert-only and safe.

Gate after steps 1, 4, 5, 6: `bbox baseline` (P5 runs `bbox indox test all`).

## Open

- Rule 5 `SUPPLIER_MAIL` is a ~135-entry inline `inList([...])` — unusable in a grid cell. Needs a
  first-class sender-list editor or a referenced list.
- `tag_rules` has `"VALIDATION STATUS"` / `"VALIDATION ERRORS"` columns nothing populates. A rule
  linter (parse + dry-run against a sample message) is cheap and high value in the new UI.
- No rollback for a bad rule edit: `TABLE_UPSERT` is insert-only for non-settings tables, so
  re-seeding does not update. Consider a `previous` snapshot in the options bag.
