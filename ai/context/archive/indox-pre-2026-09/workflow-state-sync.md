# Workflow state sync — "active" vs "published" vs "draft" in n8n

> TL;DR — when you say a workflow is **"active"**, you mean **it actually runs** (its
> trigger is listening). In n8n 2.x that requires **two** DB facts, not one:
> `active = true` **AND** it is **published** (`activeVersionId` is set). Setting only
> `active = true` makes a **draft** that *looks* active in the UI but **never runs**.
> the push paths (`bbox n8n push all` bulk SQL, `bbox n8n push <app>` API activate) set both, so "active" means what you expect.

## The terminology (this is the confusing part)

n8n 2.x split a workflow's "on/off" into two fields on `workflow_entity`:

| Field | Meaning | Set by |
|---|---|---|
| `active` (bool) | the **toggle** — "this workflow is meant to be on" | the UI toggle / `export:workflow` flag |
| `activeVersionId` | which **published** version is live (`NULL` = unpublished **draft**) | the **Publish** button / `publish:workflow` CLI |

A workflow registers its trigger **only when it is both `active` AND published**
(`activeVersionId` non-null, normally equal to the current `versionId`). So:

- **active + published** → **running** (what you call "active"). ✅
- **active + NOT published** (`activeVersionId IS NULL`) → **draft**: UI shows the
  toggle on, `active=true` in the DB, but n8n **never registers the trigger**. ❌
  This is a *silent false-active* — the dashboard lies.
- **not active** → off.

> So "publish" is just n8n's word for "make this active version the live one." When
> you say "published, I mean active" — correct: for us they must always go together.

## Three places report "active" — they can disagree

| Source | Query | Reflects |
|---|---|---|
| **DB column** | `SELECT count(*) … WHERE active` | the toggle only (can be a lie) |
| **UI list / `GET /rest/workflows`** | the on/off toggles | the toggle only (same lie) |
| **Runtime** | `GET /rest/active-workflows` | triggers **actually registered** (truth) |

If the DB/UI say active but the runtime list is empty → the workflows are **drafts**.
**Always trust the runtime** (`/rest/active-workflows`) for "is it really running?"

`/rest/active-workflows` lists **standalone listeners only**. Workflows invoked
*indirectly* — `executeWorkflowTrigger` sub-workflows, `errorTrigger` error-handlers,
`mcpTrigger` servers — are published+active but **won't appear there**; that's normal,
not a failure. So "all declared-active workflows are **published**" is the right
success signal, with runtime-listener count as a sanity check.

## How this deployment keeps state in sync

`./bbox n8n pull all` → exports workflows (as code) + credentials into the blueprint (the
blueprint), including each workflow's `active` flag.

`./bbox n8n push all` → restores the blueprint into a running n8n and, for every
workflow whose blueprint file has `"active": true`, sets **both** in one bulk SQL:

```sql
UPDATE workflow_entity SET active = true, "activeVersionId" = "versionId" WHERE id IN (…);
```

i.e. it **activates and publishes** in one step (publishing just means
`activeVersionId = versionId`; no extra `workflow_published_version` row is needed),
then restarts n8n so the triggers register. This is the fast equivalent of running
`n8n publish:workflow --id=…` for each one.

## Gotchas

- **Don't** "activate" by flipping only the `active` column — you get silent drafts.
- A wrong `N8N_ENCRYPTION_KEY` is **not** why workflows fail to activate — triggers
  register without decrypted credentials (creds are needed only at *run* time). Key
  drift is a separate problem → [[n8n-encryption-key-drift]].
- CI gate: `integration-n8n-active-state` checks **published == declared-active**
  (no silent drafts) AND runtime listeners > 0.

## See also
- `platform-base/n8n/hooks/{push,push-app,pull,pull-app}`, `platform-base/n8n/blueprint.yml`
- `ai/context/n8n-cli.md` (n8n CLI reference)
- `issues/n8n-active-state-publish.yaml` (the bug that motivated this doc)
