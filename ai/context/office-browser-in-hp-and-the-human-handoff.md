---
date: 2026-10-14
status: research + plan
tags: [browser42, link, hp-laptop, logins, handoff, autonomy]
sources: DGO-566, DGO-567, lnk-034, ui2-075, app-025, app-026, cap-001/002
---

# The office's useful browser — in the HP office, connected, and hand-off-able

The owner's plan (2026-10-14), verbatim:

> «התוכנית זה שהדפדפן השימושי של המשרד ישב בפיל, ויהיה מחובר לגוגל וווצאפ וגיטהאב והכל כדי לאפשר
> אוטונומיות מלאה לעזריה. בשביל החיבור הראשוני צריך לוודא שהדפדפן גם תומך בתת קישורים ובעצם מאפשר
> שיתוף קישור לחלון ספציפי ברגע של הזנת הסיסמה או אני לא רובוט שעזריה לא מצליח לעבור לבד. ככה אני
> אוכל לפתוח את הקישור מכל מקום בשנייה להזין מה שצריך ולהמשיך. תחשוב לעומק תעשה מחקר מעמיק ותרשום הכל»

In one line: **the browser that holds the real accounts lives in the HP office; it is signed in to
Google / WhatsApp / GitHub / everything so Azaria can work alone in them; and when a human step is
unavoidable (first sign-in, 2FA, "I'm not a robot", a QR), the owner gets ONE LINK — openable from
anywhere — that lands on the exact window where the human is needed, types what is needed, and lets
the agent continue.**

This document is the deep research behind that plan: what is measured today, what is missing, and the
ordered work that gets there. Every claim carries its evidence (file:line, or a command and its
output). Everything was measured 2026-10-14 from the `vps1` office unless stated otherwise.

---

## 1. What has to be true, and where each piece stands

| # | The plan needs | Today | Where it is dealt with |
|---|---|---|---|
| 1 | The useful browser runs in the HP office | ✅ done 2026-10-14 — HP declared `browser42` in its `serve:`; vps1 sees it as a remote app | DGO-566, lnk-034 |
| 2 | vps1 (and the owner anywhere) can reach that browser | ✅ over the link, and ✅ publicly through the nested console host (DNS + LE cert + SSO measured) | §3, §4 |
| 3 | Azaria can DRIVE that browser, not only watch it | ⛔ `/mcp` needs a token no link can carry today; the signed-door answer (DGO-545) is HP's suggestion | §6 |
| 4 | A link that lands on the EXACT window where a human is needed | ⛔ today's hand-off is a bare string `…/view/` — no tab, no window, no notification | §2 — the main gap |
| 5 | The browser is signed in to Google / WhatsApp / GitHub and stays that way | ◑ profile/session persistence is strong; **there is no TOTP/one-time-code support anywhere**; GitHub has a token path that bypasses the browser; WhatsApp has a QR path in the plane | §5 |

---

## 2. The hand-off: a link to the exact window

### 2.1 What identifies a "window" today

- There is **one Chromium window, always** (`start-browser.sh:186-205`, boot convergence; `:149-159`
  keeps it fitted to the work area; `guard-shared-browser.py:12-20` blocks only `Browser.close`).
  The unit a human recognizes is therefore a **tab**, not a window.
- A task's tab is a **session group**: every tab of a group carries `window.name = "b42g:<slug>"`
  (`group-manager.py:56`, applied at `:636`; `group_tabs()` re-finds it by tag at `:467-479` and
  never touches page 0, the human `/view` anchor).
- The group's identity is persisted at `data/browser42/groups/<slug>/group.json` (`:53`, `:271-272`),
  written by `touch()` (`:417-431`) and `cmd_open` which adds `url, color, tab_id, group_id`
  (`:604-610`). `bbox b42 groups` lists them (`:649-669`).
- When a group is allocated **with a URL**, the browser extension also makes it a native Chromium tab
  group titled with the slug: `extension/worker-1.2.js:74-123` — `tabs.update(tabId,{url,active:true})`
  / `tabs.create({url,active:true})` (`:77-83`), `tabGroups.update(groupId,{title,color,collapsed:false})`
  (`:107-111`). Per-slug identifiers live in `chrome.storage.local` as `session_<slug>` (`:113-120`).
- **Everything above is inside the container**: the outside doors are `docker exec` only
  (`hooks/group:13-15`, `hooks/groups`, `hooks/task:23-25`); the broker is a unix socket
  (`broker.py:25,47,77,88`). The only HTTP surface is `caddy/Caddyfile:14-42` — `/view` (fixed
  parameters, no tab parameter), `/websockify`, `/mcp`.

### 2.2 What the hand-off is today — a string, nothing more

- When a captcha round is refused: `group-manager.py:1459-1464` raises
  `captcha_attempts_exhausted` with the sentence *"hand the challenge to the owner at
  http://browser42.localhost:8080/view/"*. That is the **whole** mechanism — a generic URL inside an
  error body. No token, no slug, no tab.
- The only consumer that already speaks "a human is needed" is `apps/domains`: it returns
  `"live_view": "/a/browser42/"` beside `login_url` (`apps/domains/portal.py:165,209`), sets
  `state="needs_human_login"` (`browser_ops.py:311`), and `NEEDS_HUMAN` sessions never retry
  (`browser_session.py:27,52`). Again: the tile, not the tab.
- There is **no hand-off verb**: `hooks/task:2` lists
  `start|inspect|status|verify|finish|goto|click|extract|screenshot|read|fill|press|captcha|goal|watch`
  — no `handoff` / `human` / `view`.
- The evidence a human needs already exists: `captcha detect` saves a screenshot with its sha256 and
  crops every tile as its own picture (`group-manager.py:1401-1412`, `:1414-1437`). **The missing
  link in the chain is the address, not the evidence.**
- And when a task dies, nobody is told: `task-watchdog.py:123-140` marks `state="stalled"` and
  `:173` only prints `task stalled: <slug>`. There is no notification path to the owner at all.

### 2.3 What is missing, precisely

Bringing a tab to the front is **already possible** — `chrome.tabs.update(tabId,{active:true})` is
exactly the call the extension already makes (`worker-1.2.js:77-83`), and Playwright exposes
`page.bring_to_front()` on any page found by `group_tabs()`. Nothing about "one window always" is
broken by focusing a tab.

The chain to build is three existing things joined:

1. **slug → tab identity** (already stored: `group.json`'s `tab_id`/`group_id`,
   `chrome.storage session_<slug>`);
2. **an activate command over the broker** (the extension implements it; the broker needs the verb);
3. **one small route in front of `/view`** that takes the slug, wakes the browser, activates the tab,
   and lands the human on the view — plus a CLI verb (`bbox b42 handoff <slug>`) that prints the
   link, and the failure paths (captcha exhausted, `needs_human_login`, stalled) carrying **that**
   link instead of the generic string.

Three truths the design must respect (measured, not opinions):

- **noVNC shows a SCREEN, not a window** (`start-browser.sh:206-209`; `Caddyfile:14-18`). After the
  link focuses the right tab, the owner sees the one X display — so the promise is "the right tab is
  in front", never "only it is shown".
- **In compact presentation the tab strip is hidden.** `docker-compose.yml:23-25`
  (`BROWSER42_PRESENTATION_MODE=compact`) plus F11 sent on start (`start-browser.sh:176-183`;
  toggle in `browser-navigation.js:1-7`) means the group's name is not even visible unless the
  hand-off returns presentation to standard — so the page itself has to carry the hint.
- **The browser sleeps.** `hooks/sleep:6,30`: `BROWSER42_IDLE_SLEEP_S`, and *a `/view` visit wakes
  it*. A hand-off link must therefore go through the view (or wake explicitly) — one more reason the
  route belongs in front of `/view`.

### 2.4 The shape to build (one screen, no new model)

```
GET /handoff/<slug>            (on browser42-caddy, behind the office SSO like /view)
  → wake the browser            (the /view visit already does it)
  → broker: activate the group's tab (tabs.update {active:true}, no new window)
  → presentation: compact → standard, so the slug is visible on the strip
  → 302 to /view/vnc.html?…
bbox b42 handoff <slug>        → does the above and prints the absolute URL for a human
captcha exhausted / needs_human_login / stalled → carry that URL, not `…/view/`
```

---

## 3. The link has to open from anywhere — measured

The nested console host for the shared browser is
`browser42.hp-laptop.console.staging.digital-office.co.il` (built from the remote app's `host` by
`app.js:296-303`; the module's `embed` field is **not** used for an `external` tile, so the iframe
loads the host root). The chain behind it: console tile → vps1 edge
(`platform-base/traefik/config/zz-serve.yaml:254-263`, middlewares `authentik@file`,
`dgo-remote-hp-laptop-identity` → `X-authentik-username: akadmin`, `dgo-remote-hp-laptop-browser42-host`
→ `Host: browser42.localhost`) → service `http://browser42.hp-laptop:9003`
(`zz-serve.yaml:313-317`) → link proxy alias (`.generated/remote.override.yml:3-12`) → WireGuard →
HP's door (`apps/dgo-extend/linkproxy.py`) → HP's browser42 caddy.

| Check (from `bina-ds` on vps1) | Result |
|---|---|
| Public DNS for `console.…` and for the nested host | **A 93.184.216.5** — and a deliberately random name resolves too ⇒ a wildcard `*.console.<domain>` exists |
| TLS (`openssl s_client` → 93.184.216.5:443) | Per-host Let's Encrypt cert, `CN=browser42.hp-laptop.console.staging.digital-office.co.il`, issued **2026-10-14 09:52**, valid to 2027-01-12 |
| `curl -I https://<nested host>/` and `/view/` | **302** → `auth.staging.digital-office.co.il/application/o/authorize/?client_id=EqXEbBTn…` with `Set-Cookie: authentik_proxy_EqXEbBTn…` (host-only) |
| `curl -I http://<nested host>/` | **404 `404 page not found`** (traefik itself) — no `http → https` redirect for nested hosts |
| Local app for comparison (`http://machine.staging.…`) | 302 → auth (works) |
| Deep link into a remote tile | `#/m/browser42.hp-laptop/view/` → console opens `https://<nested host>/view/` (`app.js:1339-1341`); the router matches on `Host` only, so **any inner path is forwarded** — and `/view/` was measured 302 (SSO), i.e. routed |
| The console reading the iframe's route back | impossible: cross-origin (`watchFrameRoute` `app.js:1215-1219`), and G83 **excludes remote tiles** (`embed-route-lint.py:83`, `inventory.py:176`) |

**So, "open the link from anywhere" is two thirds built**: DNS, certificate and SSO are in place and a
path can be carried into the remote browser. What is not:

1. **The sign-in inside the frame (ui2-075).** Console and nested host have *different* authentik
   providers, and both cookies are host-only — so the console's session is not sent to the frame, and
   when the nested session expires the frame lands on the login page, which is `X-Frame-Options: DENY`
   → the owner's phone showed a grey rectangle (measured 2026-10-12,
   `issues/a-linked-office-tile-frames-a-sign-in-that-cannot-be-framed.yaml`). A **fix is alive in the
   running console** (`watchOwnHost` / `openOwnHost` in `platform-base/console/static/app.js`) — but
   it is **uncommitted** (`git status` shows ` M platform-base/console/static/app.js`, ` M …/desktop.js`),
   so a clean clone loses it. The acceptance of ui2-075 has also not been re-run at a real address.
   **Therefore: the hand-off link must be a link the owner opens AS A PAGE (top level), not only a
   frame** — that sidesteps the whole two-sessions problem.
2. **Port 80 for nested hosts answers 404** — a link typed or shared without `https://` dies.
3. **No route contract for remote tiles** — the owner's "the browser must support sub-links" is
   exactly this gap: the console can push a path in, nothing defines what the remote app reads back,
   and the gate that enforces deep links for every other app skips remote tiles.

---

## 4. The HP office as the browser's home — availability

The link history (`./bbox dgo link history`) is the honest measure of "is the useful browser there":
hourly heartbeats, and one outage in the recorded window — **down 2026-10-13 09:20 → 14:33 (5 h 13 m)**,
up since. HP is a laptop: it sleeps, it moves, its address changes (lnk-016/lnk-017, and the
2026-10-07 case where it came back as `192.168.16.100` while the record said `.102`).

That is a real constraint on "full autonomy", and it deserves an owner decision rather than an
assumption:

> **Decided by the owner, 2026-10-14** («א ברור שhp אמרתי מפורש»): **HP is the home of the useful
> browser.** The profile, the sign-ins and the accounts live there; nothing is moved to vps1 and no
> second profile is built. What follows from it, decided by the office rather than asked again:
> when HP is away, the door answers with its own card ("הלשכה לא ענתה" / "האפליקציה לא עונה",
> `apps/dgo-extend/link-proxy.py:324-334`) so the owner sees he is waiting for a machine and no
> failure is silent; the driver is HP's own agent while there is no secret-free path (lnk-035);
> and if the link history starts showing frequent outages, the decision comes back with that
> measurement instead of drifting. DGO-568.

- **HP as the home** — the accounts and the profile are already warmed there, the machine has the
  resources; the cost is that the *whole* useful browser is absent whenever the laptop is.
- **An always-on home** (a server-class machine in the office) — autonomy that does not depend on a
  laptop lid; the cost is warming a new profile there (the owner's sign-ins, once).
- **Both** — the useful browser where the owner is, the always-on one for the agent's own work
  (this is what the one-window/one-driver model supports today).

Whatever is chosen, one rule already holds and must stay: **the office browser is ONE Chromium with
ONE driver at a time** (one tab group per task, one task-runner). Its resource signature is the
largest in the office (6 containers, ~0.7–0.9 GiB RAM, `ai/context/browser42-resource-and-load-report-2026-09-22.md`),
which is exactly why vps1 does not run one (`platform.state.yaml:52` — `browser42: {state: disabled, by: user}`).

---

## 5. Being signed in — Google, WhatsApp, GitHub, everything

### 5.1 What the platform does today

- **One password flow, one site.** `LOGIN_FLOWS` contains `facebook` only
  (`group-manager.py:811-822`; `logins.py:95`). `bbox b42 task login <slug> facebook` leases the
  credential from the plane as the task-runner container (`group-manager.py:803,847-870`), types it
  over CDP, and deletes it from memory (`:1750`); it is never printed, journalled or returned
  (`:1730-1735`). **Success is "the login form disappeared"** (`:1765-1772`) — which is why a page
  that then asks for a second factor is reported as the generic `login_failed` ("the site may want a
  second factor"). A new site is one row here plus a declaration in `app.json:35-72`.
- **The two stores are bridged.** The credential plane is the source of truth and Chrome's password
  manager is a mirror for the human: `materialize` (plane → Chrome autofill) and `harvest`
  (Chrome → plane) run on every sync, with conflicts decided by HMAC fingerprints in
  `/data/browser-logins.json` (`logins.py:2-37,348-473`) and a documented refusal if a real keyring
  appears (`:39-52`).
- **The profile is the asset, and it is protected.** Two layers: the vendor's `rmtree` on the seed is
  blocked (`Dockerfile.browser`, `start-browser.sh:352-358`), and a snapshot at
  `/data/profile-snapshot` is taken every 20 s and restored on boot — a snapshot is replaced only by
  one with **more cookies** (`start-browser.sh:422-464,501,507-539`), with `.prev` beside it.
  `bbox b42 state dump|load|reset` adds an encrypted (AES-256-CBC/PBKDF2,
  `BROWSER42_STATE_PASSPHRASE`) whole-profile backup (`browser42-state.sh:73-126`).
- **There is no automatic dump after a sign-in** and `BROWSER42_STATE_PASSPHRASE` is not set in the
  live `.env` (`ai/context/setup-facebook-login.md:22-26`) — so the encrypted backup is a manual step
  that has never been taken.

### 5.2 The central gap: no one-time code anywhere

`grep -r 'totp|otpauth|one-time' platform-base/connections/` finds one line — wizard text in
`providers/30-google.yaml:15`. The provider kinds that exist are
`config, password, text-secret, oauth-client, oauth-grant, sa-key, app-password, derived, qr-session,
cert, secret` (`platform-base/connections/providers/*.yaml`). **2FA exists only as a *state* to stop
at** — `needs_2fa` in `browser_session.v1` (`ai/context/browser-session-connection.md:104-118`,
implemented in `apps/domains/browser_session.py:52`, `apps/social-list/browser_session.py:54`).

Without a one-time-code kind (a TOTP secret in the plane + a generator + the login flow typing it
when asked), Google, GitHub and any bank cannot be signed in by an agent — only by a human, every
time the session dies.

### 5.3 The three services the owner named

| Service | What a sign-in needs | What already exists | Verdict |
|---|---|---|---|
| **Google** | email → password → **2FA** → often a device-verification challenge (`ai/context/setup-google-cloud-login.md:22-56`: "auth is human-in-the-loop by default") | An OAuth broker with a real consent redirect and refresh (`platform-base/connections/app.py:1175-1230`; provider `oauth-grant` in `30-google.yaml:31-67`), a service-account key (`:69-80`), vision/Gemini keys, Gmail app-password for IMAP/SMTP (`40-apps.yaml:4-15`) | Browser sign-in = human + (missing) TOTP. **API/OAuth where it exists, browser for what has no API.** |
| **WhatsApp** | a QR scanned once from the owner's phone | In the credential plane exactly that: kind `qr-session` with Baileys inside the `chat` app (`40-apps.yaml:93-106`), live QR over `GET /api/qr/<cid>` (`connections/app.py:881-902`), disconnect (`:905-917`); the plane reports "scan QR to pair"/"paired" by kind (`app.py:503-521`) | **In the browser: nothing.** No `web.whatsapp.com` anywhere in browser42, no QR provider in its `app.json` (facebook only), and no "wait until paired" tool — the only path is manual (`/view` + eyes). `chat` is disabled in this office. |
| **GitHub** | password + 2FA (device verification) — or a token | A whole `git` app with four GitHub auth modes: `git_github_pat`, `git_github_fine_grained`, `git_github_app`, `git_github_oauth` (`apps/git/accounts.py:12-23`), installation tokens (`credentials.py:5-6,39,130-175`) and OAuth refresh written back to the plane (`:17-22,119-125`) | **Token/App, not browser.** But `git` is disabled (`platform.state.yaml`), there is no GitHub provider record in the plane, and the checkout still cannot fetch (DGO-547 / lnk-033). `git_github_oauth` has no `authorize_url` — GitHub OAuth is not wired. |

### 5.4 What "connected to everything" therefore means, honestly

- **Password-only sites**: works today (one site implemented — adding sites is small work).
- **2FA sites**: **blocked on a one-time-code kind**; until it exists, the human path is the
  hand-off link, and after a human sign-in the profile keeps the session alive.
- **QR sites**: the browser path works manually (open the page, show the view, the owner scans);
  what is missing is a verb that *waits* for pairing and reports success, and a session-lifetime
  policy (`ai/context/central-business-system-master-map.md:273-283` — creds are rewritten on
  `creds.update`, `loggedOut` deletes the session).
- **Services with an API** (Google Drive/Mail, GitHub, WhatsApp via Baileys): prefer the API path —
  the browser is for what publishes no API, which is the rule `apps/domains` already follows
  (`ai/context/browser-session-connection.md` §0).

---

## 6. Driving the browser from another office (Azaria's autonomy, materially)

The browser is in HP, the agent is in vps1. Three ways the agent can act on it, in the order they
become true:

1. **Watch it** — done: the live view crosses the link (`/view/vnc.html` → 200 with 18,186 bytes,
   title `noVNC`; `/websockify` → **101 Switching Protocols** through the door, measured 2026-10-14).
2. **Ask the HP office's agent to run the task** — works today: `bbox b42 task …` on HP, evidence
   back. This is also the only shape that respects "one driver at a time".
3. **Drive it directly over MCP** — blocked on a credential: HP's `/mcp` answers **401** without
   `Authorization: Bearer $BROWSER42_MCP_TOKEN`, and HP's agent refused to hand that token over a
   paired link for two stated reasons: the built-in hand-off (`converge._handoff_agents`) travels
   through `computers`/SSH and this pair has `machine: null`; and a permanent token to the owner's
   personal browser on a public server is the owner's decision. Its proposed shape is the platform's
   own: the door already **signs** what it delivers (`x-dgo-identity`, HMAC with the pair's secret,
   300 s — DGO-545), so `/mcp` could accept *provenance* instead of a shared secret, and revocation
   would be removing the app from `serve.only` — exactly like Plane.

---

## 7. The plan (ordered), and what is opened where

| Order | Item | What it is | Acceptance | Owner? |
|---|---|---|---|---|
| 1 | **app-057** | The hand-off link to the exact window: a route in front of `/view` that takes a slug, wakes the browser, activates the group's tab, returns presentation to standard; a `bbox b42 handoff <slug>` verb; the failure paths (captcha exhausted, `needs_human_login`, stalled) carrying that link; a notification to the owner when it happens | On a live browser: the link, opened by a human, shows the page where the human is needed (screenshot), the slug is visible on the strip, no second window is created; the captcha refusal returns the link, not a bare `/view` | — |
| 2 | **ui2-076** | Sub-links for a remote tile: the console's deep link and the app's own route agree, remote tiles are no longer excluded from the deep-link gate, and a link that is opened top-level (not framed) works from a phone | A real link opened on a phone (outside the office network) lands on the wanted screen; G83 covers remote tiles with the app's own `route` declaration | — |
| 3 | **app-058** | One-time codes: a `totp` kind in the credential plane, a generator, and the browser login flow typing the code when the page asks — plus `needs_2fa` handed to the owner when there is no secret | A login on a TOTP-protected account completes with no human and no code ever printed/journalled; without a secret the flow refuses by name and hands over the link from app-057 | — |
| 4 | **app-059** | QR pairing through the browser (WhatsApp first): a verb that opens the site, hands the owner the link, waits for pairing and reports success; a session-lifetime policy for the paired browser session | A real account pairs while the owner watches the view; the verb reports "paired" without a human saying so; the session survives a container restart and the loss is reported, not silent | scan: owner |
| 5 | **lnk-035** | Driving the linked office's browser from here: the credential path (MCP token vs door-signed provenance), which office drives when, and the "one driver" rule | `bbox b42` (or an equivalent verb) acts on the remote office's browser with no token in a command line, and the refusal names what is missing when it cannot | the permanent-token decision: owner |
| 6 | **(this doc)** | The browser's home and availability: HP sleeps (measured outage 5 h 13 m on 2026-10-13); decide the home of the *useful* browser (HP / always-on machine / both) and what the agent's own work uses | The decision is written here with its consequences; the agent's autonomy does not silently depend on a laptop lid | owner |

Already open and referenced by this work: **lnk-034** (the share itself — done), **DGO-545** (door
signing), **ui2-075** (the framed sign-in; its fix is live but **uncommitted** — this is the same
class of risk as DGO-547), **app-025 / app-026** (the browser-session layer and the social app that
consume these logins), **cap-001 / cap-002** (the captcha path whose refusal must carry the new link).

---

## 8. Decisions the owner should make

1. **Where the useful browser lives** — **decided 2026-10-14: HP** (the owner's own words, §4). The
   fallback behaviour is decided with it: a named card and a notice, never a silent failure.
2. **How the agent drives it** — a permanent MCP token for the personal browser, or the door-signed
   provenance (DGO-545) with revocation by `serve.only`. §6.
3. **How far to go on 2FA** — a TOTP secret in the office vault (more autonomy, the office holds a
   factor) or always the human hand-off (less autonomy, no new class of secret). §5.2.
4. **Whose sign-in the browser holds** — the owner's personal accounts (today) vs separate office
   accounts for the agent, which is a different risk conversation with Google/GitHub.
