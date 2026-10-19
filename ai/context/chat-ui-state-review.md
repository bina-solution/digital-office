# chat client — connection-state architecture review

**Scope**: `apps/chat/src/api/ui/chat.ejs` (the whole client), `platform-base/console/static/app.js`
(the shell's account chip), `apps/chat/chatapi/{server.js,connections_client.js,adapters/index.js}`
(what the client is talking to), `platform-base/console/app.py` (the embed proxy).

**Method**: static read of the files above plus `git log`/`git show`. Nothing was run against a live
stack; §9 lists what that leaves unproven.

**Not proposed**: a rewrite, a framework, a bundler, or a router. Every item below is justified by a
defect it prevents or a duplication it removes.

---

## 1. The reproduced bug, and its root cause

**Symptom** (owner's repro): switch connection from the CONSOLE's top-bar account chip. The chip
shows `טלגרם - בדיקה / testbot@`. The chat app's own in-app switcher still shows
`צ׳אט מקומי / שירות פנימי`, and the conversation list still shows a LOCAL conversation (`הלשכה`).

### Root cause, in one sentence

The active-connection pointer is a **file on the chat service's disk**
(`apps/chat/chatapi/connections_client.js:22-23`, `:110-116` — `/data/active.json`, written
atomically). Two independent controls write it, and **the chat client only ever reads it inside
`boot()`** (`chat.ejs:589-612`). The console writes it without telling the frame; the frame has no
listener, no re-read on focus, and no path that re-runs `boot()` for a change it did not itself
cause. There is no channel between them — no `postMessage` anywhere in the repo (verified: zero
`postMessage` and zero `addEventListener('message')` in `platform-base/console/static/`,
`apps/chat/src/`, `apps/drive/static/`, `apps/mail/mailapi/static/`).

### The exact chain

1. `platform-base/console/static/app.js:779-793` — `svcSelect()` POSTs
   `/api/svc/chat/connections/select {id}`, then calls `renderAccountBar()` to re-read the chip.
   It touches nothing else. It does not know an iframe exists (`mount` is the chip node).
2. The console proxies that to `apps/chat/chatapi/server.js:744-753` — `POST /connections/select`,
   which does `cc.select(id)` (writes the file) and `adapters.forget(id)`.
3. The chat client is not notified. `chat.ejs` has exactly four `boot()` triggers: initial load
   (`:1970`), its **own** `selectConn()` (`:820`), `window.__chatReload()` (`:631`, called from
   remove-connection `:790`, add-connection `:1164`, reconnect `:1948`/`:1951`), and
   `setEngineOperator`/`createEngineUser` (`:1448`, `:1476`). None of these can fire from a console
   click.

### Why the *conversation list* also stayed on the old connection — two different failures

This is the part that makes the bug look inconsistent, and it is worth stating precisely, because
the two halves need different fixes.

**Case A — the app was on a local connection (the repro).** Only the local backend implements
`subscribe` (`adapters/local.js:811`; telegram and baileys have no such method — verified by
signature grep). So `canSubscribe()` is true, `syncLive()` (`chat.ejs:1931-1935`) starts the
EventSource, and on `ready` the code **stops the poll entirely** (`:1919 stopPoll()`). The stream is
pinned to the old connection (`:1898-1899` sends `?connection_id=<S.active>`), so it keeps streaming
LOCAL events and never fires. **Nothing re-fetches.** The list is frozen on the local snapshot —
`הלשכה` — indefinitely. That is exactly what was observed.

**Case B — the app was on telegram/whatsapp.** No `subscribe`, so the 8s poll is running
(`:1832-1838`). `tick()` calls `loadConvs()`, which is `jf('/conversations')` with **no
`connection_id`** (`:633`). The server resolves the *current* pointer
(`server.js:513-519` → `adapters.resolveActive(pick(req))`, `pick` returns null → active file).
So within 8 seconds the list silently fills with the **new** connection's conversations while the
sidebar label, the protocol badge, the status dot, the bot card, the `newChat` gating and the
`ops` surface all still describe the **old** one. That is strictly worse than the frozen case: it is
a screen that is half one account and half another, with nothing on it saying so.

The same applies to `visibilitychange` (`:1843`) — it calls `tick()`, not `boot()`. Alt-tabbing away
and back re-reads the conversations but not the connection identity, producing Case B on demand.

### The comment that hides this

`chat.ejs:700-708` states, as the justification for keeping the in-app switcher:

> "The console renders its own top-bar chip (renderAccountBar) for a module whose declaration
> carries `service:` — drive's and mail's do. Chat's does not: its routing[].module in
> apps/chat/app.json has no `service` key, so showEmbed() is passed `undefined` and #acctChip stays
> hidden. […] on the day it does, THIS control and the chip must agree, which they will: both read
> the same /connections + /readyz off the same single active pointer."

That day was **2026-07-29**, commit `c80af853` "console: the account chip lights up for chat". It
added `"service": "chat"` to `apps/chat/app.json` (routing[0].module, present today) and `chat:
"צ׳אט"` to `SVC_HE` (`console/static/app.js:377`). `git show --name-only c80af853` touches exactly
two files: `apps/chat/app.json` and `platform-base/console/static/app.js`. **`chat.ejs` was never
updated**, so the file still explains why the bug cannot happen.

The commit message asserts the same thing: *"The chip and the in-app switcher cannot contradict each
other: both read the same /connections and /readyz off the same single active pointer."* Both read
the same pointer — but the app reads it **once, at boot**. A shared source of truth that is only
sampled on mount is a cache, and the two controls now hold two copies of it.

**Verdict**: the defect was introduced by a one-line declaration change whose stated safety argument
was wrong, and the file that would have contradicted it was not read. This is not a UI bug; it is a
missing invalidation edge.

---

## 2. The state matrix

### 2a. Every piece of client state scoped to a connection

Nine separate declarations, spread across 1,300 lines (`:533`, `:853`, `:1075`, `:1195`, `:1349`,
`:1634`, `:1832`, `:1864`, `:1870`). "Which of these is per-connection?" is not answerable from any
one region of the file.

| # | State | Declared | Per-connection? | Cleared on switch? | Where |
|---|---|---|---|---|---|
| 1 | `S.accounts` | `:533` | list is global; `activeBot` per row is per-conn | yes | `boot():598` |
| 2 | `S.active` | `:533` | **is** the pointer | yes | `boot():598` |
| 3 | `S.activeAcct` | `:533` | yes | yes | `boot():601` |
| 4 | `S.bots` | `:533` | no (global roster) | re-read anyway | `boot():600` |
| 5 | `S.convs` | `:533` | **yes** | yes, but see race R1 | `loadConvs():633` |
| 6 | `S.filter` | `:533` | UI-only, but stale on a connection with no groups | yes | `selectConn():816` |
| 7 | `S.q` (search) | `:533` | UI-only | yes (+ input value `:817`) | `selectConn():816-818` |
| 8 | `S.openId` | `:533` | **yes** — ids are not portable across connections | yes | `selectConn():816` |
| 9 | `S.openContact` | `:533` | yes | yes | `selectConn():816` |
| 10 | `S.ready` (/readyz) | `:534` | **yes** | yes | `boot():600` |
| 11 | `S.ops` (manifest) | `:534` | **yes** — gates newChat/SSE/reconnect | yes | `boot():600` |
| 12 | `S.protocols` | `:534` | no (service-wide) | re-read anyway | `boot():600` |
| 13 | `S.reachable`,`S.connErr` | `:534` | no (vault-wide) | yes | `boot():599` |
| 14 | `S.threadSig` | `:534` | yes | yes | `selectConn():816` |
| 15 | `S.booted` | `:534` | no | yes | `boot():605`, `fatal():616` |
| 16 | `S.botConn` | `:536` | yes (modal cursor) | **NO** | — |
| 17 | `BS{conn,bot,schema,saved,token}` | `:853` | **yes** (bot settings, per (conn,bot)) | **NO** | only `drawBotDetail():935-936` |
| 18 | `CONN{providers,pick}` | `:1075` | no (service catalogue) | n/a — reset in `openConnect():1082` | ok |
| 19 | `TOOLS{subs,loaded}` | `:1195` | **no**, by design — WhatsApp-bot store, documented `:1216-1217` | n/a | ok |
| 20 | `ENG{users,busy}` | `:1349` | local engine only | reset in `openEngine():1355` | ok |
| 21 | `NC{users,q,mode,picked,token,busy}` | `:1634` | **yes** — address book of one connection | **NO** | only `openNewChat():1653` |
| 22 | `_poll` timer | `:1832` | yes (mode is per-conn) | yes | `syncLive():1931-1935` |
| 23 | `_es` EventSource | `:1864` | **yes** (pinned `?connection_id=` `:1899`) | yes | `stopEvents()` at `boot():595` and `syncLive():1932` |
| 24 | `_pending{}` (optimistic sends) | `:1870` | **yes** (keyed by conversation id) | **NO — never cleared, anywhere** | — |
| 25 | Composer draft (`#ta.value`) | DOM | yes | yes, incidentally (`#thread` innerHTML replaced) | `renderThreadState():1571` |
| 26 | Conversation-list scroll pos | DOM | yes | **NO** | — |
| 27 | Export URLs in tools modal | `:1238` | pinned at modal-open | **NO** (modal stays open) | — |
| 28 | Console `_acct` cache | `console/app.js:585` | yes | on chip re-render only | `renderAccountBar():624` |

**The four that are genuinely wrong** (16, 17, 21, 24) and what each costs:

- **`_pending` (24)** — `pendingAdd()`/`pendingDone()` (`:1871-1872`) bracket a send. If a send never
  resolves (network drop mid-switch), the entry is permanent. Its only consumer is `onChange()`
  (`:1890`): `if(d.fromMe && _pending[S.openId]) return;` — a permanently-pending conversation
  **permanently suppresses its own inbound refresh on that conversation id**. Unbounded and
  self-silencing. Cheapest real bug in the file to fix.
- **`NC` (21)** — with the "new conversation" modal open during a switch, `NC.users` still lists the
  OLD connection's people, `NC.token` is not bumped, but `ncConn()` (`:1647`) reads `S.active`
  **live**. Clicking a person therefore POSTs `{user_id: <old-conn user>, connection_id: <new conn>}`
  to `/api/conversations` (`:1755-1757`). Best case a 400 in the service's words; worst case, on two
  local identities sharing one user table, a conversation opened as the wrong identity.
- **`BS` (17) / `S.botConn` (16)** — with the bots modal open during a switch, the matrix and the
  settings panel keep the previous connection's rows. `BS.token` is not bumped, so an in-flight save
  from before the switch still applies (`:1045`). Bounded blast radius (the payload carries its own
  `connection_id`, `:1044`), so this is a display lie rather than a wrong write. Still: the modal
  header says «ההתנהגות בחיבור X» (`:937`) about a connection that is no longer active.

### 2b. Every path that can change the active connection

| # | Path | Entry point | Writes pointer via | Client state re-read | Console chip re-read |
|---|---|---|---|---|---|
| P1 | In-app sidebar switcher | `acctRows():761` → `selectConn():811` | `POST api/account/select` → `server.js:113-122` | **full** — clears 8 fields (`:816-819`) then `boot()` | **no** |
| P2 | In-app phone sheet | `openConnPicker():798` → `acctRows($('#connRows'),closeModal)` → same `selectConn` | same | **full** (same function) | **no** |
| P3 | Console top-bar chip | `console/app.js:662` → `svcSelect():779` | `POST /connections/select` → `server.js:744-753` | **NONE** | yes (`:792`) |
| P4 | Console connect wizard | `console/app.js:1142`, `:1207` (rollback), `:1270` | `POST /connections/select` | **NONE** | yes, via `closeConnectWizard():839` |
| P5 | Direct `POST /api/account/select` (n8n, curl, another tab) | — | `server.js:113-122` | **NONE** | **NO** |
| P6 | Server-side auto-clear on connection delete | `server.js:249` and `:784` — `if(active===id) select(null)` | file | only if the app initiated it (`:790` `__chatReload`); **not** if the console did (`console/app.js:795-803`) | yes if console initiated |
| P7 | Server-side auto-clear on operator-off | `server.js:459-462` | file | yes if the app initiated (`:1448` `boot()`); the console has no such control | n/a |
| P8 | Implicit fallback: pointer is `null` → `cc.defaultId()` | `adapters/index.js:178`, `connections_client.js:118` | not a write — a **read-time substitution** | never observed by anyone | never |

**P8 is the "404-driven fallback" and it deserves its own line.** `resolveActive()` resolves
`connectionId || (await cc.active()) || cc.defaultId()`. So after P6/P7 null the pointer, *every*
subsequent op silently answers as `chat_local-local` — with no error, no status change, and no field
in any response that the client inspects. The design comment at `adapters/index.js:166-175` is
careful to distinguish "unset (use default)" from "broken (503)" **on the server**; the client has no
way to tell the two apart because it never looks at the `connection_id` the responses carry.

**The matrix in one line**: three of the eight paths (P1, P2, P7) re-read app state; five (P3, P4,
P5, P6-via-console, P8) do not. P3 is the one an operator uses, because it is the control the shell
puts in the top bar.

### 2c. What the responses already carry, and the client throws away

Every one of these is a free, already-shipped correctness hook:

| Endpoint | Field | Line | Client does |
|---|---|---|---|
| `GET /api/conversations` | `account: cid` | `server.js:517` | discards (`chat.ejs:633`) |
| `GET /api/manifest` | `connection_id` | `server.js:71` | discards (`chat.ejs:600` reads `ops`/`protocols` only) |
| `GET /api/readyz` | `connection_id` | `server.js:84`, `:87` | discards (`chat.ejs:604` reads `ready`/`reason`) |
| `GET /api/bots/:id/settings` | `connection_id` | `server.js:295` | **used** (`chat.ejs:956`) — the one place that does it right |
| `PUT /api/bots/:id/settings` | `connection_id` | `server.js:307` | **used** (`chat.ejs:1056`) |
| `POST /api/conversations` | `connection_id` | `server.js:508` | discards |
| `GET /api/conversation/:id` | **nothing** | `server.js:521-528` | — (the one endpoint that would need a server change) |

The bot-settings panel is the only subsystem in the client that treats "which connection did the
service answer for" as data. Its pattern is correct and is already in the file; it just was not
generalised.

---

## 3. The races

### R1 — stale `loadConvs()` overwrites fresh state (real, unguarded, hit on every switch)

```js
function loadConvs(){ return jf('/conversations').then(function(d){
  S.convs=(d&&d.conversations)||[]; renderList(); if(!S.openId) renderThreadState(); }); }
```
`chat.ejs:633`. No token, no id check, no connection check. Every caller races: `boot():610`,
`tick():1835`, `onChange():1882`, `doSend():1607`, `doBroadcast():1285`, `openAfterCreate():1800`,
`visibilitychange:1843`.

The concrete sequence: poll fires at T, switch lands at T+50ms and runs `boot()`, boot's own
`loadConvs()` resolves at T+300ms with connection B's list, the T poll resolves at T+400ms with
connection A's list — and A wins. The screen then shows connection A's conversations under
connection B's label until the next tick. `POLL_MS=8000` (`:1832`) makes the window small but it is
open on every single switch, and `boot()` fires four parallel requests before it, so the timing is
not adversarial — it is ordinary.

**The answer already contains the guard**: `account: cid` (`server.js:517`). It is thrown away.

### R2 — `boot()` has no generation token; four requests, three answers about "which connection"

```js
return Promise.all([jx('/accounts'),jx('/bots'),jx('/readyz'),jx('/manifest')]).then(...)
```
`chat.ejs:595`. If the pointer changes between the dispatch of `/accounts` and the dispatch of
`/manifest`, `S.active`/`S.activeAcct` describe connection A while `S.ops`/`S.ready` describe
connection B — **permanently**, until something reboots. The consequences are exactly the "buttons
don't match the label" complaint:

- `canStartChat()` (`:556`) gates the «שיחה חדשה» button on B's ops while `noStartReason()` (`:567`)
  names A in the explanation.
- `canSubscribe()` (`:562`) decides poll-vs-stream from B's ops, and `startEvents()` (`:1898`) then
  pins the stream to `S.active` = A.
- `canReconnect()` (`:545`) rewrites the reconnect button's label (`:1945`) from B's ops for A's
  failure.

Two concurrent `boot()`s (rapid switcher clicks, or `selectConn` racing `__chatReload`) interleave
the same way, and the *slower* one wins every field. `stopEvents()` at `:595` plus `syncLive()` at
`:609` means the later-resolving boot also tears down the earlier boot's stream and opens one for
whatever `S.active` says by then.

Both `/readyz` and `/manifest` return `connection_id`. Cross-checking them against
`acc.active` is a three-line change and would turn a silent split-brain into a re-boot.

### R3 — `refreshThread()` guards on the wrong identity

```js
function refreshThread(){ var id=S.openId; if(!id)return;
  jf('/conversation/'+encodeURIComponent(id)).then(function(d){
    if(!d||!d.messages||id!==S.openId)return; ... }); }
```
`chat.ejs:1819-1831`. The `id!==S.openId` check is correct for "the user clicked another
conversation" and useless for "the connection changed", because `S.openId` is nulled by
`selectConn():816` — so the guard passes trivially when `S.openId` is re-set by a later `openConv()`
on the NEW connection while the OLD connection's fetch is still in flight and happens to carry the
same id. Local ids are UUID-shaped and telegram ids are numeric, so a genuine collision needs two
local identities; the guard is nonetheless checking the wrong thing. `GET /api/conversation/:id` is
the **only** read endpoint that does not report its `connection_id` — a one-line server addition
(`server.js:521-528`) would make this checkable.

### R4 — `stopEvents()` is called but the fetches it was racing are not cancelled

`boot():595` closes the stream first, with a good comment. But no `fetch` in this file is ever
aborted — there is no `AbortController` anywhere in `chat.ejs`. `stopEvents()` prevents *future*
pushes; it does nothing about the four in-flight `jx()` calls from the previous boot, the in-flight
`loadConvs()`, the in-flight `refreshThread()`, or an in-flight `POST .../send`. This is what makes
R1 and R2 reachable rather than theoretical.

### R5 — an in-flight send crossing a switch

`doSend():1583-1617` captures `var convId=S.openId` (`:1590`) — good — but POSTs to
`/conversation/:id/send` **with no `connection_id`** (`:1593`). If the pointer moves between the
click and the request reaching the service, `resolveActive(null)` resolves the NEW connection and the
message is delivered to whatever conversation carries that id there, or 404s. The optimistic bubble
is already on screen. `_pending[convId]` is incremented before the write (`:1592`) and, if the
request errors at the transport level, `pendingDone` never runs (there is no `.catch`) — feeding R
#24 above.

### R6 — the stream survives its own connection being deselected from the console

`startEvents()` pins `?connection_id=` (`:1899`), which is right for the app's own switch (`boot()`
closes it first). It is exactly wrong for a console switch: the stream stays open, the server keeps a
dedicated Postgres LISTEN client alive for a connection nobody is looking at
(`server.js:351-398`), and each `change` event calls `loadConvs()` (`:1882`) which fetches the
**other** connection's list. So a message arriving on the abandoned local connection is what finally
repaints the screen with telegram's conversations. That is about as confusing as a UI can be.

### Where generation tokens DO exist (and are correct)

- `BS.token` — `:853`, bumped `:935`, checked `:951`, `:990`, `:1045`. Correct.
- `NC.token` — `:1634`, bumped `:1702`, checked `:1706`. Correct for typing; not bumped on switch.
- `_es` identity (`if(_es!==es)return`) — `:1910`, `:1914`, `:1922`, `:1924`. Correct.
- `id!==S.openId` in `refreshThread`/`doSend` — `:1822`, `:1606`. Correct for its purpose, wrong
  scope (R3).

**There is no connection generation token, and it is the only one missing.** The file demonstrably
knows the pattern in three places; connection identity is the one axis it was never applied to.

---

## 4. The shell↔app gap

The console changes the pointer server-side and the iframe never hears. Four options.

### Option A — `postMessage` from the shell, `__chatReload()` in the app

The console and the embedded app are **same-origin** (`/a/<name>/`, proxied by
`console/app.py:328` `app_proxy`), so `frame.contentWindow.postMessage(msg, location.origin)` works
with a strict origin check on both ends.

- **Cost**: ~10 lines in `console/static/app.js` (a `notifyEmbed(kind)` helper called from
  `svcSelect():792`, `svcRemove():802`, `closeConnectWizard():839`), ~8 lines in `chat.ejs`
  (a `message` listener next to the other global handlers at `:1956-1965`, calling the
  already-exported `window.__chatReload` at `:631`).
- **What it costs the app**: nothing that isn't already lost — `__chatReload()` nulls the open thread
  and re-boots, which is exactly what `selectConn()` already does for the in-app path. The two paths
  converge on one behaviour, which is the point.
- **Generality**: drive and mail have the identical gap (both ship their own `.acct-btn` sidebar
  switcher — `apps/drive/static/index.html:140`, `apps/mail/mailapi/static/index.html:172` — and
  neither has a `message` listener). One shell-side change covers all three; each app opts in by
  exporting a reload hook. An app that does not listen is unchanged.
- **Risk**: low. Failure mode is "nothing happens", i.e. today's behaviour.

### Option B — reload the frame (`f.src = f.src`)

- **Cost**: one line in `svcSelect()`. Requires **zero** app-side changes, which is its only real
  advantage.
- **What it costs**: a full app boot — blank frame for the load, all in-flight sends abandoned
  mid-request with no failure UI, scroll position gone, any open modal gone, the composer draft gone
  (chat has no draft persistence, so nothing is lost there today — but drive/mail may differ). It
  also re-runs the proxy's HTML rewrite + CSS injection (`console/app.py:370-381`).
- **Risk**: low but visibly worse. Recommend keeping this as the fallback for apps that do not
  acknowledge the message, not as the primary.

### Option C — the app re-reads on focus/visibility

**This does not solve the reported bug.** The iframe's `document.hidden` tracks the *tab*, not the
frame; clicking the console's top-bar chip never hides the tab, so
`visibilitychange` (`chat.ejs:1843`) does not fire at all. `window.onfocus`/`onblur` on the iframe's
window would fire when focus leaves the frame for the chip — but that also fires for every click on
the console rail, every theme-switcher click, and every alt-tab, and it cannot distinguish "the
pointer changed" from "the user looked at something". It would turn one missing reboot into a reboot
storm. **Reject.** (Worth doing anyway as *defence in depth*: upgrading `visibilitychange` from
`tick()` to a cheap `/accounts` check that reboots only on divergence costs ~4 lines and closes the
"another browser tab switched it" case, P5.)

### Option D — SSE carries a `connection changed` event

Three independent blockers, in increasing severity:

1. The stream is **gated on the `subscribe` op** (`chat.ejs:1934`, `adapters/index.js:55-58`). Only
   the local backend implements it. The connections you switch *to* — telegram, whatsapp — cannot
   receive the event at all.
2. The stream is **pinned to the old connection** (`chat.ejs:1899`). A "you are now on B" event would
   have to arrive on A's stream, which means the pin has to be abandoned or a second, unpinned
   control stream opened.
3. It puts a control-plane concern into a data-plane stream whose whole design comment
   (`chat.ejs:1854-1863`) is "ids only, nothing here builds a message".

The proxy is **not** a blocker any more: `console/app.py:346-405` streams `text/event-stream`
through untouched (`stream=True`, `timeout=(5,None)`, `direct_passthrough=True`). Note this makes
`chat.ejs:1902-1908` — which explains `HELLO_MS` by asserting the proxy "reads the WHOLE response
before forwarding it" — **stale**. The `HELLO_MS` guard is still worth keeping (any proxy in front of
the console could buffer), but its stated reason is fixed.

**Reject** as the mechanism for connection change; keep SSE for what it does.

### Recommendation: **Option A**, with Option B as the un-acknowledged fallback and Option C's
visibility check as defence in depth.

Why: it is the only option that (a) fixes P3 and P4 precisely, (b) generalises to drive and mail for
free, (c) costs the app nothing it does not already do on its own switch, and (d) fails safe. It does
**not** fix P5 (a direct API call from n8n or another tab) — nothing shell-side can — which is why
§3's R1/R2 guards and the visibility check are separate items rather than alternatives.

**Do not** fix this by hiding one of the two controls. Both are legitimate: the app is reachable at
its own origin (`chat.hacohen.bina-solutions.co.il`) where there is no console chip, and the shell
owns "which account" for every embedded service by design (`console/app.js:272-276`). Making them
agree is the fix; removing one is a different product.

---

## 5. Is `S` a coherent model?

**No. It is a flat bag that grew, and the boundaries in it are invisible.**

Evidence, not aesthetics:

- `S` (`:533-536`) mixes four unrelated lifetimes in one object literal spanning four lines:
  server truth (`accounts`, `active`, `bots`, `ready`, `ops`, `protocols`), derived values
  (`activeAcct` — recomputed at `:601` and again at `:653`), pure view state (`filter`, `q`),
  and a modal cursor (`botConn`, whose own comment at `:535` has to explain that it is *not*
  the active connection).
- Five more state objects live outside `S` for no stated reason (`BS`, `CONN`, `TOOLS`, `ENG`, `NC`),
  plus three bare module-level variables (`_poll`, `_es`, `_pending`). Nothing distinguishes
  "belongs in `S`" from "gets its own object" — `NC` and `S.botConn` are the same kind of thing
  (a modal's cursor) and live in different places.
- There is no reset function. `selectConn():816-819` clears eight fields **by hand**, in one
  statement, and `__chatReload():631` clears **three** of the same eight. The two paths that both mean
  "start over on a different connection" already disagree about what that means:
  `__chatReload()` leaves `S.q`, `S.filter`, the search input's value, the seg-tab selection and the
  `.mob-thread` class untouched. So removing a connection (`:790`) or adding one (`:1164`) leaves a
  search term from the previous connection filtering the new connection's list — a small, real,
  reproducible instance of "old chats still visible".
- `S.threadSig` is reset in four places (`:816`, `:631`, `:1518`, `:1604`) with no single owner.

### Proposed minimal shape — additive, in-file, no rewrite

Keep `S`. Add one boundary and one function. The point is not tidiness; it is that **"what is scoped
to a connection" becomes a list you can read**, and every path that changes connection goes through
one door.

```js
var S = {
  // ── service-wide: survives a connection switch ──────────────────────────────
  accounts: [], bots: [], protocols: [], reachable: true, connErr: '', booted: false,

  // ── per connection: everything here is invalidated together ────────────────
  conn: {
    gen: 0,           // bumped by resetForConnection(); every async answer checks it
    id: null,         // was S.active
    acct: null,       // was S.activeAcct
    ops: [], ready: null,
    convs: [], openId: null, openContact: null, threadSig: '',
    filter: 'all', q: ''
  }
};

/** The ONE door. Every path in §2b calls this and nothing else clears per-connection state. */
function resetForConnection(id){
  S.conn = { gen: S.conn.gen + 1, id: id, acct: null, ops: [], ready: null,
             convs: [], openId: null, openContact: null, threadSig: '', filter: 'all', q: '' };
  BS.token++; NC.token++;             // invalidate the two modal loaders
  S.botConn = null; NC.users = []; NC.picked = {};
  _pending = {};                       // #24 — the only place it is ever cleared
  stopEvents();                        // already correct at boot():595, now it lives with its siblings
  closeModal();                        // a modal about connection A must not survive onto B
  var si = $('#convSearch'); if(si) si.value = '';
  document.querySelectorAll('#segtabs .seg').forEach(function(x,i){ x.classList.toggle('on', i===0); });
  document.querySelector('.chat').classList.remove('mob-thread');
}

/** The guard. One line at the top of every async continuation that writes S.conn.*. */
function fresh(gen){ return gen === S.conn.gen; }
```

Then:
- `selectConn():811` → `resetForConnection(id); boot();` (its 4 hand-written lines go away)
- `__chatReload():631` → `resetForConnection(S.conn.id); boot();` (gains the 5 clears it was missing)
- `boot():589` → capture `var gen=S.conn.gen` at entry; `if(!fresh(gen))return;` before every write
  in the `.then` (closes R2)
- `loadConvs():633` → `var gen=S.conn.gen;` … `if(!fresh(gen)) return;` **and** assert
  `d.account===S.conn.id` using the field the server already sends (closes R1)
- `refreshThread():1819` → same `gen` check (closes R3)
- the new `message` listener from §4 → `resetForConnection(null); boot();`

This is ~40 lines added, ~15 removed, no new file, no framework, no build step. It does not change a
single rendering function.

---

## 6. Where the code duplicates itself

Assessed honestly — three of the six candidates named in the brief turn out to be **fine**, and
saying so matters as much as the ones that are not.

### FINE — desktop switcher vs phone sheet

They already share the row renderer: `acctRows(host, after)` (`:749-776`) is called by
`renderAcctMenu():725` and by `openConnPicker():808`, and both funnel clicks into the same
`selectConn()` (`:761`). The comment at `:747-748` states the reason and it is accurate. **No change.**

### FINE — poll vs SSE refresh paths

Both call the same two functions — `loadConvs()` + `refreshThread()` — from `tick():1835-1836`,
`onChange():1882-1891` and the `ready` handler `:1920`. Only the trigger differs. The design comment
at `:1814-1817` is correct. **No change** (beyond adding the `gen` guard inside those two functions,
which benefits both paths at once — that is precisely why it belongs there and not at the call sites).

### FINE — the four provider/protocol maps

`PROVICO`/`PROVHE`/`PROTOHE` (`chat.ejs:516-525`) look like a duplicate of the console's
`PROVIDER_CATALOG` (`console/app.js:393+`), but they are different vocabularies for different
surfaces, and the console's own comment (`:384-387`) already flags itself as a temporary home pending
`GET /providers`. Chat **does** serve `/providers` (`server.js:189-191`, one handler on two paths).
Consolidating is a console-side job, out of scope here, and already has an owner.

### REAL — the menu-entry list, written twice

`renderAcctMenu():726-745` and `openConnPicker():801-806` are two hand-maintained lists of the same
four entries, in the same order, with the same `isLocalConn(S.activeAcct)` gate on the third. The
`openConnPicker` comment (`:799-800`) says "same entries, same ORDER … so the phone and the desktop
are one control presented twice" — which is a promise the code cannot keep, because it is two
literals. Adding a fifth entry means editing both. **Collapse to one array**
(`[{icon,title,sub,fn,when}]`) consumed by both renderers: ~12 lines removed, drift made impossible.

### REAL — `provName`/`connLabel` vs the console's `connHe`/`protoFullHe`

`chat.ejs:526` + `:849` and `console/app.js:499` + `:503` compute the same two display strings from
the same `/connections` payload under different field names (`identity` vs `account_hint` — the
translation is explicit at `server.js:734-735`). This is a *deliberate* dialect boundary and the
server owns the translation, so it is not a bug. Note it, do not act on it.

### REAL — dead CSS injected by the console into chat

`console/app.py:305-314` — `APP_EMBED_CSS["chat"]` injects seven rules targeting `.sidebar`,
`.sidebar-link`, `.sidebar-link-active`, `.userbox`, `#username-display`. **None of those selectors
exist in `chat.ejs`**, which uses `aside.side`, `.side-lbl`, `.acct`, `.acct-btn`. They are leftovers
from the removed `wadmin` UI (`594af6c1 platform: remove wadmin`). The block matches nothing today,
and its comment describes recolouring "a dark vertical sidebar" that chat does not have. **Delete
it** — it is the kind of thing that makes the next person believe the console is styling the app and
look in the wrong file for a layout problem.

### REAL — two stale comments that actively mislead

- `chat.ejs:700-708` — asserts the console chip is dark for chat. False since `c80af853`. This
  comment is the single strongest reason nobody looked for the bug in §1.
- `chat.ejs:1902-1908` — asserts the console proxy buffers the whole response, making SSE impossible
  in the frame. Fixed in `console/app.py:382-405`. Keep `HELLO_MS`; rewrite the reason.

Comments are load-bearing in this codebase — they are the design record. A wrong one costs more than
missing code.

---

## 7. Minimisation: is `chat.ejs` being one file a real problem?

**Numbers first**: 1,975 lines / 150,154 bytes. CSS `:7-411` (~405 lines), markup `:413-482`
(~70 lines), JS `:483-1972` (~1,490 lines, of which a large fraction is prose comments).

### Honest verdict: **the file's length is not the cause of a single defect in this review.**

Every defect above is a *co-location* problem, not a *file-size* problem:

- The nine state declarations at `:533/:853/:1075/:1195/:1349/:1634/:1832/:1864/:1870` would still be
  nine declarations if they were in nine files — arguably worse, because "what is per-connection"
  would then require nine opens instead of nine jumps.
- The missing generation token, the missing reset door, the missing `message` listener, and the
  duplicated menu list are all things you fix by *adding* ~40 lines, not by moving 1,900.
- Splitting would not have caught the stale `:700-708` comment; only reading it would.

### Facts that bear on the decision (in case someone wants to split anyway)

- **The file contains zero EJS tags.** `grep -c '<%'` → `0`. It is rendered via
  `res.render('chat', {username})` (`src/api/controller.js:31`) and `username` is never used. The
  `.ejs` extension is currently a lie; the file is static HTML. So "it is served as one EJS template"
  is not actually a constraint — nothing is interpolated.
- **`express.static` points at a directory that does not exist.** `CONFIG.STATIC_FILES_PATH` defaults
  to `src/public` (`src/config.js:184`), mounted at `api.js:45`. `apps/chat/src/public` is absent.
  So splitting requires creating it — trivial (`Dockerfile:19` is `COPY . .`), but note that the
  mount sits **before** `isAuthenticated` (`api.js:76`), so anything put there is served
  unauthenticated. The client JS holds no secrets, so that is acceptable — but it must be a decision,
  not a surprise.
- **The proxy would cope.** `console/app.py:317` `_rewrite_abs` rewrites root-absolute `src=`/`href=`
  to `/a/chat/`, and `_inject_base` sets `<base href="/a/chat/">`, so both relative and root-absolute
  asset refs resolve. ES-module specifiers resolve against the module's own URL, which is already
  under `/a/chat/`. No proxy change needed.

### Recommendation

**Do not split the JS.** Do the §5 consolidation *inside* the file: move all nine state declarations
into one block under `S`, next to `resetForConnection()`. That captures ~90% of the navigability
benefit at ~0% of the risk, and it is the change the defects actually ask for.

**Optionally**, and only if someone is already touching this area: extract the 405 CSS lines to
`src/public/chat.css` (needs the `public/` dir + a `<link>`; one extra request through the proxy).
This is low value — nobody debugging connection state reads the CSS — and it is listed only because
it is the one seam that is genuinely clean.

**If the file is ever split for real**, the seams are already visible in the source and this is the
order that keeps each step independently revertable:

1. **CSS out** (`:7-411`) — zero coupling to anything.
2. **`api.js`** — `api/jx/jf/post/del/download` (`:486-503`) + `esc`. No state reads. Pure.
3. **`state.js`** — `S`, `BS`, `CONN`, `TOOLS`, `ENG`, `NC`, `_pending`, `resetForConnection`,
   `fresh`. Must come *after* §5 has consolidated them; splitting the current nine declarations
   into a file just relocates the problem.
4. **`live.js`** — poll + SSE + `syncLive` (`:1807-1939`). Already a self-contained block with one
   entry (`syncLive`) and two exits (`loadConvs`, `refreshThread`).
5. **`modals/*.js`** — bots (`:836-1060`), connect (`:1062-1173`), tools (`:1175-1330`), engine
   (`:1332-1478`), new-chat (`:1618-1805`). Each already owns its own state object and a single
   `openX()` entry.
6. **Last, and only if it still seems worth it**: the switcher + list + thread renderers.

The value/risk ratio drops sharply after step 1. Steps 2–6 buy readability that step §5 already
bought, at the cost of five new files, an `express.static` mount that is currently dead, and a load
order that has to be right.

---

## 8. Recommendations, ranked by (value / risk)

| # | Change | Prevents / removes | Files | Size | Risk |
|---|---|---|---|---|---|
| **1** | Fix the two stale comments (`chat.ejs:700-708`, `:1902-1908`) | The reason nobody looked for §1. Zero code risk, highest information value per byte in this list. | `chat.ejs` | ~15 lines | none |
| **2** | `resetForConnection()` + `S.conn.gen` + `fresh(gen)` guards in `boot`, `loadConvs`, `refreshThread` | R1, R2, R3, and state items 16/17/21/24 in §2a. Also fixes `__chatReload()` leaving a stale search term. | `chat.ejs` | ~40 add / ~15 del | low — additive; every guard's failure mode is "re-render once more" |
| **3** | Assert `d.account === S.conn.id` in `loadConvs()` | R1 at the source, using a field the server already sends (`server.js:517`). One line. | `chat.ejs` | 2 lines | none |
| **4** | Shell→frame `postMessage` on select/remove/wizard-close + `message` listener calling `__chatReload()` | **The reported bug** (P3, P4, P6-via-console). Generalises to drive + mail. | `console/static/app.js`, `chat.ejs` | ~18 lines | low — fails to today's behaviour |
| **5** | Clear `_pending` in `resetForConnection`, and add `.catch(pendingDone)` to the send in `doSend():1593` | Item 24: a permanently-pending conversation permanently suppresses its own inbound refresh. | `chat.ejs` | 3 lines | none |
| **6** | Send `connection_id` on `/conversations`, `/conversation/:id`, `/send`, `/read` (the client already does it for `/users`, `/events`, `POST /conversations`) | R5, and makes R1/R3 impossible rather than merely detected. Server side needs no change — `pick()` (`server.js:38`) already honours it on every route. | `chat.ejs` | ~6 lines | low |
| **7** | Delete `APP_EMBED_CSS["chat"]` (`console/app.py:305-314`) | 7 rules matching nothing; misdirects the next layout investigation. | `console/app.py` | −10 lines | none |
| **8** | Collapse the two menu-entry literals (`:726-745` / `:801-806`) into one array | Desktop/phone drift, structurally. | `chat.ejs` | −12 lines | low |
| **9** | Return `connection_id` from `GET /api/conversation/:id` (`server.js:521-528`) | The last read endpoint that cannot be validated; unblocks the strong form of R3's guard. | `server.js` | 2 lines | low — additive field |
| **10** | Upgrade `visibilitychange` (`:1843`) from `tick()` to a cheap `/accounts` + reboot-on-divergence | P5 (n8n or a second tab moved the pointer) — the one path no shell change can reach. | `chat.ejs` | ~6 lines | low |
| **11** | Consolidate the nine state declarations into one block (§5, no behaviour change) | Makes "what is per-connection" readable; prerequisite for any future split. | `chat.ejs` | move-only | low |
| 12 | Extract CSS to `src/public/chat.css` | Navigability only. No defect. | `chat.ejs`, new dir | ~405 moved | low, and note the pre-auth static mount |
| — | *Split the JS into modules* | **Not recommended.** No defect in this review is caused by file length; see §7. | — | — | — |

Items 1–5 are a single coherent sitting and close the reported bug plus every race found. 6–10 are
independent and individually revertable. 11–12 are hygiene with no defect attached.

---

## 9. What I could NOT verify

Static reading only. Specifically unproven:

1. **The exact repro sequence was not executed.** §1 Case A (SSE open, poll stopped, list frozen) vs
   Case B (poll running, list silently swaps) is inferred from `syncLive():1931-1935` +
   `stopPoll():1919` + the op grep showing `subscribe` only on `local.js:811`. Which case the owner
   hit depends on whether the app was on a local connection at the time — the reported symptom
   (`הלשכה` still listed, i.e. frozen) matches Case A. **Both should be reproduced before fixing**,
   because Case B is the more damaging one and is not what was reported.
2. **Whether the console chip and the in-app switcher were ever seen to agree after a console
   switch** — i.e. whether some path I did not find (a proxy cache-busting reload, an SSO
   re-navigation) sometimes reboots the frame. `showEmbed()` (`console/app.js:277-287`) sets
   `f.src = url` on every `openModule()`, so navigating away from `#/m/whatsapp` and back **does**
   reload the frame and would mask the bug. That is consistent with "very buggy" rather than
   "always broken".
3. **Timing of R1/R2 in practice.** The windows are real but unmeasured. `POLL_MS=8000` and a
   4-request `Promise.all` are the only inputs I have; actual latency through
   traefik → console proxy → chat has not been observed.
4. **Whether two local identities can produce colliding conversation ids** (R3's severity). This
   needs `adapters/local.js` id-generation read in full plus the schema; I only confirmed
   `LocalChatBackend` is constructed per `selfId` (`adapters/index.js:150-151`).
5. **`_pending` leak in practice** (item 24) — the code path requires a transport-level rejection of
   the send POST. `post()` → `jx()` (`:491-494`) converts a network failure into a resolved
   `{ok:false,status:0}`, so `pendingDone()` at `:1594` **does** run on a network error. The leak
   therefore needs a *thrown* rejection or an unloaded page mid-flight. Lower severity than I first
   assessed; still worth the 3-line fix, but it is not the smoking gun.
6. **Drive and mail** — I confirmed they ship their own `.acct-btn` switchers
   (`apps/drive/static/index.html:140`, `apps/mail/mailapi/static/index.html:172`) and have no
   `message` listener, so they have the same structural gap. I did **not** read their state
   management, so "the §4 fix generalises" is an architectural claim, not a verified one.
7. **No UI-level regression test exists for this.** `apps/chat/tests/chatapi_routes.test.js` covers
   `POST /connections/select` at the route level (`:584-586`) and the pointer-clearing on delete
   (`:168`, `:175`). `digital-office/sim/flow-qa.py` has **no** chat suite (grep for `chat` in it:
   no hits). So none of the recommendations above have a harness that would catch a regression —
   which is itself worth a line in whatever plan follows this document.
8. **`platform.state.yaml` / compiled `console.modules.yaml`** were not read; I took the `service:
   chat` key from `apps/chat/app.json` and `c80af853`'s commit message, which claims the compiled
   registry carries it. If the deployed console is running an older compiled registry, the chip would
   still be dark there and the bug would not reproduce on that host.
