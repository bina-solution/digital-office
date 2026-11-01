# Login setup — Google Cloud Console (via browser42)

Minimal recipe for getting an authenticated Google session into the shared
browser42 Chromium so an agent can read the GCP console. The session persists in
the `cloakprofile` volume, so this is a **one-time, human-in-the-loop** step.

## Pattern (applies to any auth-gated site)

1. **Open the window for the user.** Drive the live-view tab (page 0 — the tab
   `/view` renders) to the login URL so the form is waiting when they connect:
   ```bash
   docker exec -i browser42-browser-shlomo-laptop python3 - <<'PY'
   from playwright.sync_api import sync_playwright
   with sync_playwright() as p:
       b = p.chromium.connect_over_cdp("http://localhost:9222")
       ctx = b.contexts[0]
       page = ctx.pages[0] if ctx.pages else ctx.new_page()
       page.bring_to_front()
       page.goto("https://console.cloud.google.com/", wait_until="domcontentloaded", timeout=60000)
       print("URL:", page.url)
   PY
   ```
   Google redirects to `accounts.google.com/.../signin` when unauthenticated.

2. **Prompt the user, then WAIT — don't hand off.** Tell them:
   - Open **http://browser42.localhost/view/**, enter noVNC password
     `BROWSER42_VNC_PASSWORD` (from `.env`).
   - Sign in (email → password → 2FA) right in the window — the view is interactive.

3. **Poll until logged in** (run in background; foreground `sleep` is blocked).
   Done = the live-view tab's URL host becomes `console.cloud.google.com`
   (NOT `accounts.google.com` — note the sign-in URL embeds the console URL in its
   `continue=` param, so match the host *prefix*, not a substring):
   ```bash
   for i in $(seq 1 90); do
     url=$(docker exec -i browser42-browser-shlomo-laptop python3 - <<'PY'
   from playwright.sync_api import sync_playwright
   with sync_playwright() as p:
       b = p.chromium.connect_over_cdp("http://localhost:9222")
       ctx = b.contexts[0]
       page = ctx.pages[0] if ctx.pages else ctx.new_page()
       print(page.url)
   PY
   )
     case "$url" in https://console.cloud.google.com*) echo "LOGGED_IN"; exit 0;; esac
     sleep 10
   done
   echo "TIMEOUT"; exit 1
   ```

4. Once `LOGGED_IN`, run the read-only sweep (projects, billing, compute, IAM,
   activity) on `new_page()` tabs and screenshot into `/data/output/`.

## Notes
- Never type the user's credentials yourself unless they explicitly hand them over
  AND ask you to; auth is human-in-the-loop by default (2FA needs their device).
- Session survives container restart/recreate (lives in `cloakprofile`). To move it
  to another box, dump/load with `production/browser42/browser42-state.sh`.
- See [browser42-cli.md](browser42-cli.md) for the full CDP/Playwright driving guide.

## ⚠️ Connecting n8n Google credentials locally — use `http://127.0.0.1:5678` ONLY
When re-authing n8n Google OAuth credentials (Gmail/Sheets/Drive) on the **local** stack,
**open the n8n UI at `http://127.0.0.1:5678` — NOT `n8n.localhost`** — and log in there before
clicking "connect". Reason: Google rejects `http://n8n.localhost` as a redirect URI ("must end
with a public TLD"), so the OAuth callback is forced to `http://127.0.0.1:5678/...`; n8n's callback
needs the session cookie on that same `127.0.0.1` origin, or it returns `Unauthorized`. The n8n
container is published on host loopback (`ports: 127.0.0.1:5678:5678`) for exactly this. The
`n8n.localhost` route is unchanged for everyday UI use. (browser42-automated onboarding already
does this on the `127.0.0.1:5678` origin via an in-container forwarder.)
Full write-up + closed issue: [incoming-documents-onboarding.md](incoming-documents-onboarding.md) §8c,
[../../issues/n8n-google-oauth-localhost-callback.yaml](../../issues/n8n-google-oauth-localhost-callback.yaml).
