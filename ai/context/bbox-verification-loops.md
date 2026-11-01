# bbox — verification loops

A catalog of end-to-end scenarios that exercise the deployment infrastructure across **stateful
condition combinations** (fresh/existing · key same/drifted · secrets present/missing · creds
working/needs-reauth · changes from files vs the n8n UI · single/multi-machine). Each loop is a
runnable regression test: **steps** (terminal `bbox` / `browser42` scripts / agentic browser42 tasks)
and the **expected** result. Several encode bugs already found+fixed — keep them green.

Conventions: `bbox …` from repo root (Debian or Git-Bash/WSL). `B42 = docker exec -i browser42-browser-${DEPLOYMENT_NAME} python3 - <<'PY' … PY` (CDP/Playwright). "agentic" = drive browser42 via the agent to do a UI task. Owner login = `N8N_OWNER_EMAIL` / `N8N_OWNER_PASSWORD` from `.env`. n8n OAuth must use the `http://127.0.0.1:5678` origin.

---

## A. Lifecycle / setup

### L1 — Fresh clone, first run
**Pre:** no Docker volumes for this deployment. **Steps:** `bbox install <debian|windows>` → `bbox run` → `bbox onboarding`. **Expect:** traefik-network created; stack healthy; owner bootstrapped from `.env`; 114 workflows imported + 62 published; `onboarding` ends "owner is set"; `bbox verify` reports missing keys + which OAuth creds need re-auth. (Regression: owner-bootstrap must work on a host with **no host-side node** — parsed in-container.)

### L2 — Stop / start preserves data
**Steps:** `bbox status` (note counts) → `bbox stop` → `bbox run` → `bbox status`. **Expect:** containers down then up; workflow/cred/tag counts identical; no re-auth needed (volumes kept).

### L3 — Reset then rebuild (same key)
**Steps:** `bbox b42 dump /tmp/b42.enc` (preserve browser login) → `bbox reset --force` → `bbox run` → `bbox onboarding`. **Expect:** fresh volumes; owner re-bootstrapped; workflows restored; **env-managed creds reseed and work**; OAuth creds restored from the local cred-state cache **iff `N8N_ENCRYPTION_KEY` unchanged** (else flagged for re-auth). `bbox b42 load /tmp/b42.enc` restores the browser session.

---

## B. Credentials & encryption key (the stateful core)

### L4 — ★ Gmail OAuth stateful across reset (same key)  *(the canonical loop)*
**Pre:** browser42 logged into the Google account (one-time human step). **Steps:**
1. **browser42 / agentic:** open `http://127.0.0.1:5678`, log in as owner, open the Gmail credential, "Connect my account", complete Google consent (pick account → tick all scopes → Continue).
2. `bbox n8n verify` → Gmail shows **token present**.
3. `bbox n8n pull` → the git-ignored `production/n8n/.credentials-state/` cache captures the full encrypted Gmail blob.
4. `bbox reset --force` → `bbox run` → `bbox onboarding`.
5. `bbox n8n verify`.
**Expect:** after reset, Gmail OAuth is **still connected** (restored from cache, decrypts under the unchanged key) — **no re-auth needed**. (Regression: the manifest-only-creds bug that silently lost OAuth on reset.)

### L5 — Re-auth all 4 Google creds → survive reset
**Steps:** browser42-reauth Gmail + Sheets + Drive + Sheets-Trigger (the `127.0.0.1:5678/rest/oauth2-credential/auth?id=<id>` flow) → `bbox n8n verify` (all token-present) → `bbox n8n pull` → `bbox reset --force && bbox run && bbox onboarding` → `bbox n8n verify`. **Expect:** all 4 restored, none need re-auth (same key).

### L6 — Encryption-key DRIFT
**Steps:** change `N8N_ENCRYPTION_KEY` in `.env` → `docker compose up -d --force-recreate n8n` → `bbox n8n status` → `bbox n8n push` → `bbox n8n verify`. **Expect:** `status` flags **fingerprint mismatch**; push **reseeds env-managed creds** (they work under the new key); OAuth creds **can't decrypt** → `verify` lists them for re-auth; after browser42 re-auth they work. (This is the "develop on different machines" reality.)

### L7 — Missing secret in .env
**Steps:** blank `REDIS_PASSWORD` (or `SETTINGS_AUTH_PASS`) in `.env` → `bbox n8n push` → `bbox verify`. **Expect:** reseed writes the empty value; `verify`/a workflow run flags redis/settings broken **loudly**; restoring the secret + `bbox n8n push` fixes it.

### L8 — .env ↔ .env.ex parity drift
**Steps:** add `FOO_KEY=bar` to `.env` (not in `.env.ex`) → `bbox verify dependencies`. **Expect:** `[config]` warns "`.env` keys absent from `.env.ex`: FOO_KEY". Reverse (key in `.env.ex` missing from `.env`) also warned.

### L9 — Credential deleted in the n8n UI
**Steps (agentic browser42):** in the n8n UI delete a credential → `bbox n8n push`. **Expect:** push (create-if-missing) re-creates it from the cred-state cache (full blob, works) or the manifest (shell → re-auth). Existing working creds untouched (non-destructive).

---

## C. Dev loop (blueprint = code)

### L10 — Edit a workflow file → push → round-trip idempotent
**Steps:** edit a node label in `production/n8n/workflows/<id>.json` → `bbox n8n push` → confirm live reflects it → `bbox n8n pull` → `git diff production/n8n` is **empty**. **Expect:** change applied + published; round-trip clean (volatile versionId/updatedAt stripped; creds manifest-only). (Regression: 135-file pull churn.)

### L11 — Manual UI edit (Save/publish) → pull captures
**Steps (agentic):** edit a workflow in the UI and **Save** (publish) → `bbox n8n pull` → `git diff` shows the change in that workflow file. **Expect:** published UI edits are captured.

### L12 — Manual UI edit, draft-only → pull does NOT capture
**Steps (agentic):** make a node change in the UI but **don't Save** (or only "execute step") → `bbox n8n pull`. **Expect:** the draft change is **not** in the blueprint (only published versions export). Documents the gotcha: agentic edits must go through files→push, or UI Save.

### L13 — Add a new workflow file → push
**Steps:** drop a new `production/n8n/workflows/NEWID.json` (active:true) → `bbox n8n push` → `bbox n8n status`. **Expect:** imported, count +1, published if active.

### L14 — Delete a workflow file → push is upsert; clean-recreate enforces
**Steps:** `rm production/n8n/workflows/<id>.json` → `bbox n8n push` → `bbox n8n status` (live still has it → **drift** reported) → `bbox n8n clean-recreate --force` → status clean (live == blueprint). **Expect:** push never deletes (safe); clean-recreate makes live exactly match the blueprint.

### L15 — Tags: file→push and UI→pull
**Steps:** change a workflow's `tags` in its file → `bbox n8n push` → UI shows new tags (native `import:workflow`). Then add a tag in the UI → `bbox n8n pull` → file reflects it. **Expect:** tags are declarative both directions.

---

## D. Multi-machine / portability / ops

### L16 — Two-machine git drift
**Steps:** remote receives a commit (e.g., CI auto-publishes `.ci-cd/`) while you have local commits → `git pull --rebase origin <branch>` → `git push`. **Expect:** clean rebase, exec bits preserved, push succeeds. (We hit this repeatedly — keep it smooth.)

### L17 — browser42 state portability
**Steps:** `bbox b42 dump out.enc` on machine A → move `out.enc` → `bbox b42 load out.enc` on machine B (passphrase from `.env` `BROWSER42_STATE_PASSPHRASE`). **Expect:** Google/login sessions present on B without re-login. Survives `bbox reset` if dumped first.

### L18 — Pull-from-broken-instance guard
**Steps:** force the instance to 0 workflows (or right after a failed import) → `bbox n8n pull`. **Expect:** pull **REFUSES** ("instance has 0 workflows … would WIPE the blueprint"), blueprint files untouched. `--force` overrides. (Regression: a pull from an empty instance wiped the blueprint.)

### L19 — onboarding crash-resilience (push restarts n8n)
**Steps:** `bbox onboarding` (push restarts n8n at its end). **Expect:** verify **waits/retries** for n8n's REST to return; **no `ECONNREFUSED` crash**; ends with a real readiness verdict (`owner is set` / `⚠ NOT READY`), not a blind "done".

### L20 — Owner bootstrap on a host with no node (WSL)
**Steps:** on WSL (no host `node`), fresh instance → `bbox onboarding`. **Expect:** "owner created" (detection runs **in-container**). Previously this silently skipped → no account.

---

## E. Agentic browser42 / document pipeline (end-to-end)

### L21 — Email → saved document (the product happy path)
**Steps:** send a test email with a PDF attachment to the tenant Gmail (Gmail API with the connected token, or via browser42 Gmail UI), labeled per the Scanner's query → wait a scan cycle → check the tenant's Drive `gmail_docs_dest_folder`. **Expect:** Scanner tags it, Downloader saves the file to Drive, a row is upserted to the incoming-docs sheet. (Depends on Phase-1 de-hardcode for a fresh tenant: labels-by-name + Settings-driven IDs.)

### L22 — Provision a brand-new tenant (new Google account)
**Steps (agentic):** browser42 Google login (new account) → GCP OAuth client + consent + test user → re-auth the 4 creds → onboarding provisions Drive folders + settings spreadsheet + base Gmail labels → write IDs into Settings → `bbox n8n verify`. **Expect:** `settings webhook` returns the **new** folder IDs; pipeline operational on the new account.

### L23 — Agentic: toggle a workflow active in UI → pull
**Steps (agentic):** open n8n UI, toggle a workflow's active state, Save → `bbox n8n pull` → the file's `active` flag matches. **Expect:** active-state round-trips through the blueprint.

### L24 — Agentic: edit the settings Google Sheet → webhook reflects it
**Steps (agentic):** open the settings spreadsheet in browser42, change a folder URL → call `GET /webhook/setting?key=…` (Settings Auth basic-auth). **Expect:** the new value is returned (config plane reads live from the sheet).

---

## F. Failure surfacing (nothing happens silently)

### L25 — n8n not running
**Steps:** `docker stop n8n-${DEPLOYMENT_NAME}` → `bbox n8n status` / `bbox n8n verify`. **Expect:** graceful "n8n not running — bbox run" (no stack trace). Restore with `bbox run`.

### L26 — Login rate-limited
**Steps:** run `bbox n8n verify` ~6× quickly. **Expect:** once rate-limited, verify prints "could not authenticate (… rate-limited …) — re-run", **not** a crash. Waits a minute → green again.

### L27 — No .env present
**Steps:** (in a scratch copy) remove `.env` → `bbox run` / `bbox onboarding`. **Expect:** bootstrap `.env` from `.env.ex` with a warning to fill secrets; does not proceed silently with broken config.

---

### How to use
- After any infra change, run the relevant loops (D/F are fast + non-destructive; A/B are heavier).
- B4/B5 (OAuth-survives-reset) and B6 (key drift) need the one-time browser42 Google login.
- CI already runs the fresh-setup path (A1/A3 equivalent) every push; these loops cover the local/WSL/agentic cases CI can't.
