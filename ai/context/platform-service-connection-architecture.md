# Platform services own their connections (drive / mail) — target architecture

**Problem this kills.** Today n8n holds the Google credentials, so `connections` must *inject* the
OAuth grant into n8n's 4 creds over its REST API. That path produced two silent, invisible-in-CI
bugs in one afternoon (missing `N8N_OWNER_*` env; `Secure` cookie unusable over internal http) and
still 401s. And the backend choice (`DRIVE_BACKEND`, `GMAIL_BACKEND`, `GMAIL_IMAP_MODE`) is baked
into router constants **at n8n-push time** — a build-time switch for a runtime fact.

Both disappear if the **platform service owns the connection**.

## Separation of concerns

| service | owns | never knows |
|---|---|---|
| **secret-base** (`connections`) | credentials + the OAuth broker; connections tagged by `protocol`; the vault | what a "folder" or "label" is — zero domain logic |
| **platform service** (`drive`, `mail`) | domain ops; one adapter per protocol; which connection is **active**; readiness | orchestration, business rules |
| **n8n** | orchestration (when/why) | credentials, providers, backends — it depends on **readiness**, not auth |
| **console** | UX: show active account, pick another, launch "connect new" | secrets |

One sentence: **secret-base = who you are · platform service = what you can do · n8n = when to do it.**

## Contracts

**Protocol** = capability + auth method. The service declares which it speaks:
- `drive`: `drive_google_oauth`, `drive_google_sa`, `drive_local`
- `mail`: `mail_gmail_oauth`, `mail_imap_app_password`, `mail_imap_local`

**Connection** (in secret-base): `{id, protocol, label, account_hint, status}` + secret in the vault.
`connections` already has the vault, kinds, and the OAuth broker — it gains a `protocol` tag and
`GET /api/connections?protocol=drive_*`.

**Platform service API** (same shape for drive and mail):
```
GET  /manifest              -> {service:"drive", protocols:[...], ops:[...]}
GET  /readyz                -> 200 iff active connection resolves AND its probe passes  <- n8n gates on THIS
GET  /connections           -> compatible connections + which is active   (asks secret-base)
POST /connections/select    -> {id}   (the "one selected account" shown in the UI)
POST /<op>                  -> domain op; optional `connection_id` overrides the active one
```
`/readyz` is the whole contract n8n needs. n8n's `depends_on` + a readiness gate replace every
credential concern.

## Local-first default, external on request

Each service ships a **wired local adapter** (`drive_local` -> localdrive/supabase-storage;
`mail_imap_local` -> GreenMail). A fresh install works with **zero** configuration — no Google, no
keys. Onboarding then *offers* "connect Google Drive": the broker mints a `drive_google_oauth`
connection, the user selects it as active in the drive UI. This is exactly the fresh-VPS story we
could not tell today.

## Endless connections, one active

Many connections may exist per protocol. Exactly one is **active per service** (that is what the
platform UI shows). Ops accept an optional `connection_id`, so a sync pair can pin a specific
account later without changing the model — "endless in potential", one selected by default.

## What this deletes

- `inject_into_n8n()` + the 4 injected n8n Google credentials (bugs #8/#9 become unreachable)
- `DRIVE_BACKEND` / `GMAIL_BACKEND` / `GMAIL_IMAP_MODE` env switches and their bake-in at n8n-push
- `CREDENTIALS_OVERWRITE_DATA` for Google
- "re-auth each credential in the UI" as an operator concept

## Incremental path (each step shippable)

1. **`mail` first — it is already 90% there.** `inbox` has the op+params contract and an
   oauth/imap/router split ([[inbox-canonical-contract]]). Add `/manifest`, `/connections`,
   `/connections/select`, `/readyz`; read creds from secret-base at runtime instead of env. Prove
   the pattern on one service.
2. **`drive`**: promote `localdrive` to the `drive` service (it already owns native storage), add
   the `drive_google_oauth` adapter, move `driveApi01`'s logic in.
3. **n8n**: routers collapse to thin HTTP callers to `drive`/`mail`; delete the env switches; gate
   on `/readyz`.
4. **console**: account picker per service (lists compatible connections; "connect new" hands off
   to the broker with the right protocol).

Ordering matters: 1 proves the contract cheaply, 3 is what removes the build-time switch, and only
after 3 can `inject_into_n8n` be deleted.

Related: [[inbox-canonical-contract]], [[integration-api-backend-unification]],
[[indox-api-routing-and-architecture]], [[connections-google-oauth-injection]],
[[localdrive-ui-and-native-storage-verdict]], [[fresh-vps-staging-bringup]].
