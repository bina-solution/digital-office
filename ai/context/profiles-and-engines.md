# Engines, profiles and profile-connections — the cross-app contract

**Status:** design contract, derived from a full read of `apps/mail`, `apps/drive`, `apps/chat` and
`platform-base/connections`. Any agent touching multi-profile in any app builds against this. If
something here is wrong, change this file first and say so — do not diverge silently.
Supersedes the people-first framing in [identity-and-people.md](identity-and-people.md); platform
users and per-user permissions are explicitly OUT of scope here (see §7).

## 1. Vocabulary (use exactly these words)

| Term | Definition | Today's implementation |
|---|---|---|
| **Engine** | a backend implementation. **Private** = we run the process. **Remote** = someone else does. | `protocol` string: `mail_imap_local`, `drive_google_oauth`, `chat_wa_baileys` |
| **Profile** | a named identity *on* one engine | connections-service **instance**, `<protocol>-<8hex>` |
| **Profile-connection** | the binding that makes a profile the one an app acts as | `/data/active.json` in each app |

Two different things in this codebase are both called "connection". The **provider catalogue**
(49 rows, one id → **one env var**) is a credential list, and it is structurally incapable of holding
a second account — `GMAIL_IMAP_APP_PW` can only hold one value. The **instance** model is the profile
plane. Never say "connection" unqualified.

## 2. The law

> **A private engine can have N profiles because we own its process.
> A remote engine can have N profiles only if its client is instance-scoped rather than process-scoped.**

Scored against reality — and note the diagonal, which is the opposite of what the model predicts:

| App | Private engine | Remote engine |
|---|---|---|
| mail | **1** — `_build` returns bare `LocalBackend()`, secret discarded, creds from `LOCALMAIL_*` env | **N** ✓ per-instance `GmailBackend(user, pw)` |
| drive | **1** — `drive_files` has 11 columns, none an owner/profile discriminator | **N** ✓ per-instance adapter + own token cache |
| chat | **N** ✓ `chat_local-<userId>` → `LocalChatBackend({selfId})` | **1** — Baileys is a process-global singleton socket |

**The private engines — the ones we own and could make perfect — are mostly the ones that cannot
create profiles.** Only chat got it right, and chat is the one whose remote engine is broken.

## 3. Reference implementations — copy these, do not reinvent

| Concern | Take it from | Why |
|---|---|---|
| Two-tier capability contract | **chat** `CANONICAL_OPS` + `PROTOCOL_OPS` + `opsFor(backend)` | absence of a method *is* "unsupported"; the manifest is derived from the live object, so it cannot drift |
| UI that changes shape per engine | **chat** `canStartChat()` / `canReconnect()` / `noStartReason()` | disables the control **and names the connection in the reason**. Nothing else does this |
| Single choke point | **drive** `resolve_active()` | `/readyz` and every op agree "by construction", not by convention |
| Fail loud on a dangling pointer | **drive** | see §4 |
| Dangling pointer surfaced *as a row* | **drive**, **mail** | `/connections` can never report an `active` id absent from its own list |
| Probe without selecting | **drive**, **mail** | a profile is *verified*, never merely "added" |
| Backend cache keyed by credential **fingerprint** | all three | a rotated password invalidates the pool with no restart |
| Token write-back, **merge by default** | **drive** | a refresh returns no `refresh_token`; a blind overwrite downgrades renewal into "reconnect your account" |
| `status 0 ≠ 404` | **chat** | unreachable → use cached credential; 404 → **delete** the cache. Serving a deleted account's token keeps the app running on credentials the operator believes they removed |
| Degrade, never throw | **chat** | empty *shaped* answer with non-enumerable `reachable`; a write that did not happen never reports `ok:true` |
| Private-engine admin **separate from the switcher** | **chat** `/api/engine/users`, bound to the local backend | CREATE-a-profile cannot be misfired at a remote engine |

## 4. The invariant that outranks everything

From drive's `resolve_active()`, after a real incident on 2026-07-17:

> the pointer said Google, `/readyz` answered `200 {"ready":true,"connection_id":"drive_local-local"}`,
> n8n gates on `/readyz` alone — and every drive op wrote the owner's real business documents to a
> local disk he was never looking at, **green the whole way**.

**An unset pointer means "use the default". A broken pointer means "not ready" — never a fallback.**
Local is a legitimate answer to *nothing is selected*, never to *the selected account is missing*.
Mail and chat already state this rule; it must survive every refactor.

## 5. What to build

**(a) Make private engines instance-scoped.** This is the whole fix for the diagonal in §2.
- **chat** is the reference: `chat_local-<userId>` → `LocalChatBackend({selfId})`. Already works.
- **mail**: `LocalBackend` must take its mailbox from the *instance*, not `LOCALMAIL_*` env. Then
  `POST /mailboxes` can mint the instance in the same operation — the password is already in the
  request body. Until then, mailboxes created in the UI **are not reachable as profiles**, and
  `POST /connections` will still accept a `mail_imap_local` instance with a secret, store it, list
  it, let you select it, and serve the same one mailbox. That is a live silent-wrong-answer path.
- **drive**: `drive_files` needs a profile discriminator. INDOX already proved the pattern —
  a column defaulting to the existing instance name so the rollout is a **no-op**, plus
  `scripts/refactor/tenancy-lint.py` to catch unscoped queries. Drive's `POST /connections` refusal
  of `drive_local` is correct *until* that column exists.

**(b) Make remote engines instance-scoped.** Chat's Baileys owns a process-global socket
(`src/globals.js`), so every `chat_wa_baileys-*` instance resolves to the same phone number whatever
its label says. Needs a socket registry keyed by connection id with per-connection auth dirs. The
adapter layer does not block this; `baileyes_app.js`/`globals.js` do.

**(c) Creating a private profile registers its profile-connection in the same operation.**
Today `mailboxd` creates addresses and `connections` holds profiles and *nothing joins them*.

**(d) Give profiles honest health.** Instance `status` is written once at creation as `"ok"` and
**never updated**. Every non-active profile claims healthy — a lie the mail UI, the console chip and
INDOX all render. Add `PUT /api/instances/<id>/status` + `last_checked`, written by the owning
service after any probe. The services already run the probe; nothing records the answer.

**(e) Make Engine a first-class noun, served by each service.** The console's `PROVIDER_CATALOG` is
marked in-code **"⚠ TEMPORARY HOME"** and is the only place mapping protocol → provider + auth method
+ form fields. Chat and mail serve `/providers`; drive serves it; they disagree in shape. Either a
`GET /engines` on every platform service or a registry compiled by `reconcile.py` from `app.json`,
the way `connections.providers.yaml` already is. This is probably the highest-leverage single change.

**(f) Stop parsing ids as data structures.** `/-local$/`, `/-local$|-env$/`,
`cid.rsplit("-",1)[0]`, `"gmail" if conn_id.startswith("mail_")`. Add explicit `app`, `engine`,
`is_private`, `deletable` fields. `protocol` stays as the derived compatibility field.

## 6. Do not build

- **Do not add profiles as provider-catalogue rows.** The consumption path is environment variables,
  which are process-global. Any "make providers multi-instance" work is a rewrite that lands you back
  at an active pointer.
- **Do not move the active pointer into the connections service.** It is app-local on purpose: a
  connections outage must degrade a list, not un-select every app's account. Two separate
  postmortems in this repo are about exactly this boundary.
- **Do not let connections create private-engine profiles.** Chat wrote down why: *"you cannot create
  a user on WhatsApp, you pair a device."* Engine administration only exists for an engine we own.
- **Do not put profile management in "חיבורים ומפתחות".** It is organised by *kind of secret*, not by
  account, and shows zero instances today. It should gain a read-only "connected accounts" list; the
  switcher and wizard stay in the app/console.

## 7. Explicitly out of scope (for now)

Platform users (authentik) and per-user resource permissions. The active pointer is **one global
scalar per deployment** today — two operators behind the same SSO share it, and one switching accounts
silently changes the other's next request. Chat is honest about the same gap: selecting an identity is
*impersonation without authentication*. Do not solve this now, but **when adding a scoping dimension
to the pointer, key it so a session/user can be added later without a second migration.**

## 8. Live bugs found during this review (verify before acting)

1. **chat: the WhatsApp bot is attached to nothing.** `CHAT_WA_CONNECTION_ID` defaults to
   `'wa-baileys'` and is set nowhere in the repo; `protocolOf('wa-baileys')` → `null` → `no_bot`.
   The code's own comment warns this "silently switches the production number off the moment it
   deploys — the worst kind of regression, because nothing errors". Group-mention handlers run
   earlier and would mask it. **Needs live verification.**
2. **chat: Telegram has no inbound path.** `ingest()` is public and documented but nothing calls it —
   no poller, no webhook. Send-only.
3. **chat: local identities render a remove `×` that 404s** — `chat_local-alice` is sent to the vault.
   The correct gesture is the operator toggle.
4. **console `POST /connections` can mint an unusable chat instance** holding `{username,password}`,
   because the console wizard has no chat entries and falls back to a generic card.
5. **drive: the storage meter is dead code** — backend returns `{used, limit}`, frontend gates on
   `STORAGE.total`, which never exists.
6. **drive: `owner`/`shared` in the UI is fictional** — ported from the sim, no backend field. The
   people filter is permanently empty; everything reads "רק לך יש גישה".
7. **connections: `GET /api/instances/<id>/secret` is not policy-gated.** Any container on the network
   can enumerate profiles and pull every OAuth grant. The broker protects the catalogue plane and
   leaves the instance plane open.
8. **One Google grant mints two instances holding *copies* of the same token dict**, with no link.
   Mail and drive each write back to their own copy; a refresh-token rotation strands the other.
9. **`drive_google_sa` does not exist** — it appears in two design docs and zero lines of code.
