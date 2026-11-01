# Connecting to something that has no API — the browser-session protocol (`browser_session.v1`)

Some of the services this business depends on publish no API at all. The office's own domain
registrar is the worked example: Internic (InterSpace Ltd) serves a Laravel panel behind a WAF, has
no documented endpoint, and holds nothing of the `.co.il` zone anyway — verification of that is in
`apps/domains/AGENT.md`. For those, the only automation that is both possible and legitimate is the
one a human already performs: **the owner logs in once, in the office's own browser, and an app then
acts inside that logged-in session** — on the owner's behalf, in the owner's account, through a
browser that never leaves the office.

This document is the contract that makes that reusable. It is written to be consumed by ANY app
(domains today; social networks, couriers, government portals, banks tomorrow), not by one.

## 0. What this is NOT (decided once, in writing)

* **Not a cloud automation service.** Apify (and every SAAS RPA in its class) would run the browser in
  somebody else's infrastructure, which means the owner's cookies — and any 2FA they completed — are
  decrypted on a third party's disk. Research on 2026-09-23 concluded it is the wrong tool for this
  office: it is built for scraping public content, it has no actor for an Israeli registrar panel, it
  has no persistent logged-in browser profile across runs, and residential proxies actively HURT here
  because the whole point is to keep the same session fingerprint the owner logged in with.
* **Not a password store.** No app ever asks for the portal's password. The password is typed by the
  owner into a real browser, once, and never touches a vault, a config file or an agent.
* **Not a scraper.** The target is the business's own account, the actions are few and deliberate
  (a handful per day at most), and every one of them is logged with its evidence.

## 1. The nouns

| noun | meaning |
|---|---|
| **session** | one logged-in browser context for one origin, kept alive by the office's browser app (`browser42`: one shared Chromium, one persistent profile, CDP on `:9222`) |
| **connection instance** | a credential-plane row, protocol `browser_session`, whose secret is a POINTER: `{endpoint, token_connection, origin, group, labels}` — never a cookie and never a password |
| **portal script** | a versioned, declarative list of steps that performs ONE operation (list domains, write a record). Data, not code — so it can be reviewed, diffed, fixed without a release, and shipped with the app |
| **action** | one run of one portal script, with a result and, when it fails, the screen that proves it |

## 2. The connection

An app that wants a browser session declares it like any other connection (nothing new to learn):

```jsonc
// app.json
"use": [{ "capability": "browser", "strength": "wants", "after": false, "dependency": "weak" }],
"connections": [{ "id": "browser-session-portal", "required": false }]
```

The instance itself is created in the ordinary place (`connections` / the app's own screen), with
this secret shape:

```jsonc
{
  "endpoint": "http://browser42-caddy:80/mcp",   // where the office browser is reachable, in-network
  "token_connection": "browser42-mcp-token",     // the credential-plane id holding the bearer token
  "origin": "https://portal.internic.co.il",     // the ONE site this session speaks for
  "group": "domains-internic",                   // tab group: isolates this app's tabs from the agent's
  "labels": { "portal": "internic" }
}
```

**The token is referenced, never copied** (`token_connection`): the vault stays the single copy of
every secret, and an instance created for a session cannot go stale against a rotated token.

## 3. The operations

Every provider of `browser_session` serves exactly these five ops. They are deliberately about a
PAGE and a SESSION, never about domains or posts — that is what keeps the protocol app-agnostic.

```
POST /session/state    {origin}                       -> {authenticated, url, title, evidence}
POST /session/open     {url, group}                   -> {url, title, text, forms[], links[]}
POST /session/read     {url, locator, many}           -> {values[]}
POST /session/act      {url, steps[], verify}         -> {state, steps[], evidence, verify}
POST /session/screen   {url, group}                   -> {png_base64 | path}
```

`/session/act` is the only mutating op, and its steps are the portal script's language:

```jsonc
{ "id": "write-record",
  "action": "goto|click|fill|select|press|wait_for|assert|read|eval",
  "locator": { "role": "button", "name": "שמור", "label": "…", "testid": "…", "css": "…" },
  "value": "…",                       // fill/select/press
  "expect": { "url_matches": "…", "status": 200, "text_contains": "…" },
  "timeout_ms": 15000 }
```

**Locator order is part of the contract, not a style preference**: `role`+`name` first (what the
page says to a human and to a screen reader), then `label`, then `testid`, and `css` only as a last
resort. A CSS path is a transcription of today's markup; an accessible name is what the page MEANS,
and it survives the redesign that breaks the CSS.

## 4. The result — and the states that matter more than success

```jsonc
{ "state": "ok",
  "steps": [{ "id": "…", "ok": true, "ms": 812 }],
  "verify": { "read_back": "1.2.3.4", "expected": "1.2.3.4", "match": true },
  "evidence": { "url": "…", "screenshot": "…", "at": 1790000000 } }
```

The states are the useful half, because a portal breaks in ways that are not "an error":

| state | meaning | what the app must do |
|---|---|---|
| `ok` | performed AND verified by reading the value back | nothing |
| `needs_human_login` | the page is a login screen (or redirected to one) | STOP; tell the owner, with a link to the live browser view; never retry |
| `needs_2fa` / `captcha` | a human step is required mid-flow | STOP, same as above |
| `session_expired` | was authenticated, now is not | STOP once, notify, offer the login link |
| `selector_missing` | the flow changed (the page no longer has the control) | STOP; this is a script to fix, not a click to retry |
| `assert_failed` | a step ran, the effect did not happen | STOP; keep the evidence |
| `rate_limited` / `blocked` | the portal said slow down / refused | back off; never hammer |
| `unknown_error` | anything else | STOP, keep the evidence |

**A non-`ok` state that needs a human NEVER retries automatically.** A portal that has just told us
"this is not you any more" must not be asked ten more times: that is how an account gets locked, and
the lockout costs the owner far more than the action was worth.

**Verification is reading the value back** — from the page after the write, and (for DNS) from a
public resolver afterwards. "The click succeeded" is not evidence that anything changed.

## 5. Security rules (not negotiable)

1. The browser stays inside the office. No session, cookie or screenshot leaves it except as an
   explicit artifact the owner asked for.
2. The CDP port is loopback-only. Anything that can reach it can drive the browser: it is inside the
   container network and is never published.
3. One group per app. Groups share the profile (that IS the feature) but not the tabs, so two apps
   driving the same browser cannot navigate each other's pages.
4. Every action is logged with who asked, what ran, what the page said, and when — the log is the
   answer to "what did the office do on my behalf".
5. Actions are few and deliberate. A portal script that wants to loop over hundreds of items belongs
   in front of the owner, not in a scheduler.

## 6. Adding a portal (the recipe)

1. Get the login done once: open the office browser's live view and log in like a human.
2. `POST /session/state` — confirm `authenticated: true`. If it is not, the whole feature is "log in
   again", and the app says so instead of failing obscurely.
3. `POST /session/open` on the page the operation starts from, and READ ITS STRUCTURE — forms,
   buttons, table headers. The office never guesses a selector; it observes one.
4. Write the steps as data (a portal script), with `verify.read_back` pointing at the field that
   proves the write.
5. Run it once with the owner watching, then keep the evidence.

This is why an app that depends on this contract does not need a new browser, a new login, or a new
credential — only a script.
