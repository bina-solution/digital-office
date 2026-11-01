# Automation Infrastructure as Code — the unified dev loop

> The n8n automation stack is developed as code: the **git blueprint is the source of truth**, the live
> instance is a projection of it. This doc is the working contract for agentic/human development.
> Companion: [incoming-documents-architecture-and-productization.md](incoming-documents-architecture-and-productization.md).

## The loop (always, in order)
1. **`bbox n8n pull all`** — capture the host (incl. human UI edits) into git as code files. Commit as "capture host state".
2. **Edit the blueprint** — the git-tracked `production/n8n/workflows/*.json`, `blueprint.yml`, `compose`, `.env(.ex)`. **Not** the live UI/DB as the canonical change.
3. **`bbox n8n push all`** — apply to the host. Safe/idempotent (see below).
4. **Verify on host** — creds connect, workflows active/published, health workflows pass.

**Invariant we keep proving:** `push` from clean git → `pull` → `git diff` empty, and verify green. Every cycle re-proves push fully overwrites and aligns.

## Credential model — 3 classes (NEVER commit secrets)
Git holds credential *entities* (id/name/type) so workflows resolve by id. Secrets come from `.env`:

1. **Env-codified** — reseeded from `.env` on every push via `blueprint.yml` `credential_overrides`
   (`PATCH /rest/credentials/<id>` re-encrypts under the **current** key → survives `N8N_ENCRYPTION_KEY` drift).
   **All 19 non-OAuth creds are here.** Local-routed ones point at in-network services
   (`redis`, `n8n-postgres`, `http://n8n:5678/...`); remote ones route to `.env` keys.
2. **OAuth-bootstrapped** — the 4 Google creds (Gmail/Sheets/Drive/Sheets-Trigger). Per-account consent +
   per-machine tokens → can't be codified. Bootstrapped per-env via the `127.0.0.1:5678` consent flow.
   `push` never overwrites them (see hardening).
3. **Per-instance secrets** — e.g. the n8n API key (`n8n account` cred). Env-**routed** (`${N8N_API_KEY}`) but
   the value is minted per instance (scoped, expiring) — like OAuth, bootstrapped not committed.

## `n8n-push` hardening (what makes the loop SAFE)
- **Credentials = create-if-missing.** `import:credentials` UPSERTS by id; re-importing the git blob would
  overwrite an already-re-authed cred with an **old-key** secret and re-break working OAuth. Push now imports
  ONLY creds whose id isn't already in the DB; existing creds are left untouched and env-managed ones are
  refreshed by the reseed step. **Verified:** after push, *"all 23 already exist — none re-imported"* and
  Gmail OAuth still works.
- **Reseed** env-driven creds from `.env` (19/19) every push.
- **Workflows** import → **publish** (`activeVersionId = versionId`) → restart so triggers register.

## Gotchas (learned the hard way — don't repeat)
- **Live REST `PATCH /rest/workflows` edits are draft-only and do NOT survive** pull/push (export captures the
  published version). Agentic workflow edits MUST go through **files → push** (push publishes). The UI "Save"
  publishes, so human UI edits ARE captured by pull.
- **`export:credentials --decrypted` is all-or-nothing** — it aborts if ANY cred in the DB is key-drifted.
  Test creds **individually at runtime** (refresh-token + cheap API call for OAuth; `/rest/credentials/test`
  with resolved data for the rest), never via batch decrypt.
- **Env-specific resource IDs** (Google Sheet/Drive IDs, Gmail `Label_…` IDs, webhook hosts) hardcoded in
  workflow JSON make the blueprint environment-locked. Keep them OUT of files; resolve from Settings/`.env`
  at runtime (Phase 1 de-hardcode). Re-applying local IDs as file edits would pin the blueprint to one env.
- `n8n-push` must NOT be skipped for one-off live edits — that creates the very divergence the loop prevents.

## Verified state (2026-06-18)
- 23 credentials total: **19 env-managed** (reseed 19/19) + **4 OAuth-bootstrapped**.
- Hardened `n8n-push`: non-destructive cred import ✓, OAuth survives push ✓, publishes 62 active workflows ✓.
- Connect-tested OK: Redis, Postgres account, N8N DB, n8n account (scoped key). Env-routed but awaiting
  value/service: OpenAI, Telegram, Ollama, WAdmin, Priority×2, Document AI, Kafka (placeholders / services not deployed).
- 13 unused credentials deleted; `n8n-pull` `community_nodes` count bug fixed.

## Next (productization)
Phase 1 de-hardcode (labels-by-name, Settings-driven resource IDs) → makes the blueprint portable across
tenants. Then a one-click `onboarding` CLI (`pull`/`push`/`status`/`verify`/`onboard`). See the
productization plan in the companion doc.
