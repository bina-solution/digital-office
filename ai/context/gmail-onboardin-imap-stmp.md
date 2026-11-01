# Gmail onboarding for IMAP/SMTP automation (app-password — no Gmail API/OAuth)

> Why: the Gmail **API** layer is quota/OAuth-fragile (per-user 250 u/s, insert=25u, daily caps, token
> re-auth, restricted scopes, 429 cascades). **IMAP read + SMTP send via a 16-char app password** sidesteps
> all of it. See plan + service in `apps/inbox/`, n8n layer = workflows *gmail api - oauth* /
> *gmail api - imap smtp* / *gmail api* (router). Reference: `data/inbox-smtp.zip` (verify_gmail.py).

## What an account needs to be automation-ready (one-time, per account)
1. **2-Step Verification ON** (App passwords require 2SV).
2. **App password** created (16 chars) — Google account → Security → *App passwords*
   (`https://myaccount.google.com/apppasswords`). Name it e.g. `n8n-automation-imap`. Store the 16 chars
   (no spaces) as `GMAIL_IMAP_APP_PW` in `.env`; set `GMAIL_IMAP_USER` to the address.
3. **IMAP enabled** — Gmail → Settings → Forwarding and POP/IMAP. (Google now keeps IMAP always-on; no
   explicit toggle. Confirmed by a successful `imaplib` login.)
4. **Verify** — `python3 data/_runs/imapsmtp/verify_gmail.py` (pointed at the account's `.env`): expects
   ALL PASS (IMAP auth/read/search, folder list, SMTP send, round-trip).

## Accounts
- **person8@example.com — DONE (verification account).** 2SV on (since 2023-06-05), app password
  `n8n-automation` created, IMAP confirmed. App-pass lives in `data/inbox-smtp.zip:.env` and is wired
  into the repo `.env` as `GMAIL_IMAP_USER`/`GMAIL_IMAP_APP_PW`. `verify_gmail.py` → **ALL PASS** (auth,
  read 10.8k msgs, search, 21 mailboxes incl `[Gmail]/*` + Hebrew user labels in modified-UTF-7, SMTP send,
  round-trip). Used to build + verify the whole IMAP gmail layer end-to-end.
- **person2@example.com — DONE (active INDOX tenant account).** 2SV on; app password named
  `indox-imap` created at `myaccount.google.com/apppasswords` on 2026-06-22 and IMAP-verified (login OK,
  211 inbox msgs, 32 mailboxes incl `[Gmail]/*` + the full INDOX label set: English automation labels
  `saved-invoice-doc`/`balance-doc-saved`/`handeld-by-gdd`/… and the Hebrew ones
  `לטיפול-אוטומציה-שמירת-מסמכים`/`באמצע-טיפול-אוטומציה`/…). Wired into repo `.env` as
  `GMAIL_IMAP_USER=person2@example.com` + `GMAIL_IMAP_APP_PW` (secret, gitignored); `inbox`
  recreated and `/healthz` reports `user=person2@example.com`. The 16-char value is in `.env` only.
  **ROTATED 2026-06-25:** new app password `indox-imap-2` created via browser42 (CDP create+capture),
  written to `.env` `GMAIL_IMAP_APP_PW`, inbox recreated; direct IMAP verified (login OK, INBOX 540
  msgs, noop OK). Note: docker healthcheck can read `unhealthy` while the single gunicorn gthread worker is
  blocked warming its IMAP conn during an OVERQUOTA window (8s healthz timeout) — cosmetic; auth is fine.
  The 4 scheduled gmail SCANNERS (Actions indoxGmailActionsScanner01 / Balance Sheets m52MK8jdeU1KvJX0 / Documents
  vBcSCddTDnvbuOZi / Links errpzoZI8QWC1B0f) were DEACTIVATED (live + files active=false) to stop the
  OVERQUOTA recycle loop until the sync-refactor gmail processors replace them ([[indox-sync-refactor-v1-design]]).
  **Capture recipe (what finally worked):** the page re-verifies the account password — the user entered it
  once in the `/view` window, then (browser42 now fast — see below) immediately drive Chromium: focus the
  visible "App name" text input, type the name via `page.keyboard.type` (Material input rejects `fill()`),
  click **Create**, and read the 16-char value out of the page body (regex `[a-z]{4} [a-z]{4} [a-z]{4}
  [a-z]{4}`). Speed matters — the re-verify session expires, so do create+capture in one fast pass.

## How I drove the browser42 onboarding (for reference / re-use)
```bash
docker start browser42-browser-… browser42-mcp-… browser42-caddy-… browser42-reaper-…
# CDP up at localhost:9222 inside browser42-browser; drive Chromium via playwright connect_over_cdp
docker exec -i browser42-browser-… python3 - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.connect_over_cdp("http://localhost:9222"); page=b.contexts[0].new_page()
    page.goto("https://myaccount.google.com/apppasswords")   # -> re-verify password screen
PY
```
Gotchas: use `new_page()` (page 0 is held by the live view); multiple Google accounts may be signed in
(account chooser) — pick the right one; the app-passwords page always re-verifies the password.

## Security
App passwords grant full mailbox access — treat like a password. Keep only in `.env` (gitignored), never in
git/workflows. Revoke at `myaccount.google.com/apppasswords` if leaked. Rotating = create new, update `.env`,
recreate `inbox`.
