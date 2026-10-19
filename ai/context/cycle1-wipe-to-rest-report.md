# Cycle 1 — E2E wipe-to-rest report (2026-07-12)

Goal: verify a **one-command deploy on a new env with no external secrets**, then onboard INDOX
(Drive/Gmail/Gemini) via the console install page, inject into live Drive+Gmail, watch it sync to rest.
Run on the local Windows/Docker-Desktop host, `DEPLOYMENT_NAME=shlomo-laptop`, `*.localhost` over http.

## Per-step outcome

| Step | Status | Evidence / note |
|---|---|---|
| **1. Full wipe** | ✅ | `down` + `docker volume rm` of every app/data/supabase/connections volume. **Preserved** browser42 `cloakprofile` (the Google login) — a full `down -v` would have destroyed it. |
| **2. One-command deploy** | ⚠️ works, but **not one command** | Needed a secret-gen pre-step (see findings). After that: 44 containers up, 33 healthy; core (connections/console/n8n/supabase/authentik/apitools) all healthy; ledger `/business`→200 off freshly keygen'd supabase. |
| **3. Install window** | ✅ | `console.localhost` business `onboarded=false` → app routes to `#/m/install`; renders RTL install wizard driven by the connections plane. |
| **4. Fill onboarding** | ⛔ **blocked (external)** | Exact install blockers: `google-workspace-grant`, `gemini-key`, `gmail-app-password`, `whatsapp-baileys`. browser42 login intact (**person2@example.com**), but Google anti-abuse blocked automated Gemini-key creation ("The request is suspicious"). See findings 6–7. |
| **5. Inject 3× Drive+Gmail** | ✗ not reached | Depends on step 4 (Drive OAuth + Gmail app-pw). |
| **6. Auto-sync** | ✗ not reached | — |
| **7. INDOX page shows docs** | ✗ not reached | — |
| **8. Reach rest** | ✗ **cannot, by design, without creds** | 107 active scanners fire on schedule; 41 executions unfinished, churning against absent Google/Gmail (inbox: `Empty username or password`). A fresh deploy with no creds does NOT settle — it retry-loops. |

## Findings — why "one-command deploy, no external secrets" isn't true yet

1. **`.env.ex` + identity does not boot.** `BROWSER42_MCP_TOKEN` is required with no compose default →
   `docker compose` fails interpolation on `up`/`down`. Other machine secrets are **placeholders**
   (`change_me_…`), used as-is (connections auto-mint only fires on *empty* env, and base-infra services
   read `.env` directly, bypassing the plane). Supabase `ANON/SERVICE/JWT` placeholders are **invalid
   JWTs** — storage rejects them.
2. **The only working fresh-secret path is `scripts/ci-env.sh` + `scripts/supabase-keygen.py`** — and
   it's **CI-only** and hard-wired to **local mocks** (`DRIVE_BACKEND=local`, `GMAIL_IMAP_MODE=local`).
   `bbox run` / `bbox onboarding` do **not** generate machine secrets or run supabase-keygen.
   For this cycle I generated machine secrets inline (openssl) + ran `supabase-keygen` + set live-Google
   backends (`DRIVE_BACKEND=google`, `GMAIL_BACKEND=imap`, `GMAIL_IMAP_MODE=gmail`).
3. **n8n workflows aren't loaded by the web flow.** `bbox n8n push` (CLI) restored 112 workflows / 107
   active. The install page does not do this.
4. **`connections` reports `google-oauth-client: healthy src=env` on a placeholder** (`your-google-clie…`)
   — it only checks non-empty, not that it's a real GCP client. Misleading green.
5. **Supabase is a separate compose** (`production/compose.yml → supabase/docker-compose.yml`); a bare
   `docker compose down -v` on the main files won't wipe it (its keys/data need explicit handling).
6. **Google anti-abuse blocks automated key creation on browser42.** AI Studio → Create key returned
   "Failed to generate API key, The request is suspicious." Clipboard-read of the existing masked key
   (`…Yyeg`, project `bina-incdocs-onboard`, **Free tier**) is also blocked. The existing key may be the
   same `AQ.Ab8…` value already known-invalid (rejected by Google — see [[gemini-key-invalid-in-env]]).
7. **Google OAuth grant needs a real client + redirect registration**, not just consent — the connections
   broker uses its own redirect URI which must be registered in the GCP OAuth client. Placeholder client
   makes `/oauth/start` a non-starter.
8. **No "pause until onboarded" guard** → a credential-less fresh deploy churns active scanners forever
   instead of resting.

## Recommended next steps (before cycle 2)

1. **Make secret-gen part of the one command.** Fold `ci-env.sh`-style machine-secret generation +
   `supabase-keygen` into a `bbox init`/`bbox onboarding` prereq, parameterised by a **profile**
   (`ci-local-mock` vs `live-google`). Add `BROWSER42_MCP_TOKEN` (+ any other required-no-default var) to
   the generated set. Then `bbox onboarding` really is one command from a blank host.
2. **Auto-load workflows on fresh deploy** — wire `bbox n8n push` into `bbox onboarding` (it already
   restarts n8n), or expose a "load automations" action on the install page.
3. **Fix the oauth-client probe** — validate the value looks like a real client id (`…apps.googleusercontent.com`)
   so the install page flags the placeholder as `needs_action` instead of green.
4. **External creds — provide out-of-band, not via browser automation** (Google flags automated key ops):
   - *Gemini*: paste a valid `AIza…` key into the install page (or the connections API). The current
     `.env` key is invalid; browser42 creation is anti-abuse-blocked.
   - *Google OAuth*: register the connections-broker redirect URI in the GCP client, then complete consent
     in browser42 (consent-click is a different flow than key-creation — may not be blocked; test it).
   - *Gmail app-pw*: try the dedicated `scripts/_b42_apppw.py` helper (account-security flow, distinct from
     AI Studio) before concluding it's blocked.
5. **Add an onboarding gate** so scanners stay paused until `install_blockers` is empty → a fresh deploy
   reaches a clean rest, and sync starts the moment creds land.

## State handoff
- Backup of the pre-wipe `.env` (149 real keys) is in the session scratchpad (`env-full-backup.bak`);
  restore + `docker compose … up -d` to return to the prior working stack.
- Current stack = the fresh minimal-secrets deploy described above (live-Google backends, external creds
  blank). browser42 still logged into person2@example.com.
