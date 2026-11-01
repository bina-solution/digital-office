# Platform service + secret-base contract (v1) — IMPLEMENTATION SPEC

Frozen so secret-base, `drive` and `mail` can be built in parallel. Design rationale:
[[platform-service-connection-architecture]].

## 0. Nouns

`connection` (an account/instance) → `container` (folder | label) → `item` (file | message).
A **protocol** = capability + auth method: `drive_google_oauth`, `drive_local`, `mail_gmail_oauth`,
`mail_imap_app_password`, `mail_imap_local`.

## 1. secret-base (connections service, :8990) — NEW endpoints

Connection instances live in the existing vault, under key `instances`. Existing single-id
providers are untouched (back-compat).

```
GET  /api/instances?protocol=drive_*        -> {instances:[Instance]}
POST /api/instances                          {protocol,label,secret:{...},account_hint?} -> {id}
DELETE /api/instances/<id>                   -> {ok:true}
GET  /api/instances/<id>/secret              -> {protocol, secret:{...}}   # service-only, in-network
PUT  /api/instances/<id>/secret              {secret:{...}, replace?:bool} -> {ok:true}
```

```jsonc
Instance = { id, protocol, label, account_hint, status: "ok"|"needs_action", created_at }
```
- `id`: `<protocol>-<8 hex>`; secrets NEVER returned by the list endpoint.
- The OAuth broker (`/oauth/<cid>/start|callback`) gains `?as_instance=1`: on callback it CREATES an
  instance of the provider's protocol holding the tokens, instead of injecting into n8n.
- `account_hint`: e.g. the Google email; display only.
- `PUT .../secret` = **token write-back**, service-only and in-network like the GET. The service that
  renews an OAuth access token persists it here, so the vault stays the one copy (§5a) instead of the
  renewal dying with the container — and so a rotated `refresh_token` can never strand the other
  service. **MERGE semantics by default**: a Google refresh returns only `access_token`/`expires_in`,
  and a blind overwrite would drop the `refresh_token`. `{"replace":true}` overwrites wholesale (real
  re-consent only). `protocol`/`label`/`account_hint`/`created_at` are immutable here; the record
  gains `updated_at`. 400 on an empty `secret{}`, 404 on an unknown id, and it NEVER returns the
  secret. Callers (`localdrive.update_secret`, `inbox.put_secret`) treat it as best-effort: a
  failed write-back logs and keeps serving the in-process token, never fails the op.
  ⚠ The vault is a whole-file read-modify-write; this route holds a process-local lock over its
  read→write window, which is enough only while connections runs single-process (it does).

## 2. Platform service (drive :8975, mail :8970) — REQUIRED endpoints

```
GET  /manifest      -> {service:"drive", protocols:[...], ops:[...], capabilities:{...}}
GET  /readyz        -> 200 {ready:true, connection_id} | 503 {ready:false, reason}
GET  /connections   -> {active:<id|null>, connections:[Instance]}     # proxies secret-base by protocol
POST /connections/select   {id}  -> {ok:true, active:id}
POST /connections          {protocol,label,secret{}} -> {id}          # add (proxies secret-base)
DELETE /connections/<id>   -> {ok:true}   # removing the active one clears active
POST /<op>          {...params, connection_id?}  -> op result
```
- **Active pointer** persists in the service (`/data/active.json`); `connection_id` on any op
  overrides it for that call.
- `/readyz` = active resolves AND its adapter probe passes. **This is the only contract n8n needs.**
- The local adapter is ALWAYS available as instance id `<proto>-local` (synthetic, no secret) so a
  fresh install is ready with zero config.

## 3. Ops (canonical, provider-agnostic)

`drive`: `list, download, upload, move, update, delete, createFromText` (exactly today's
driveApi01 op names — n8n keeps working).
`mail`: `search, get, addLabels, removeLabels, listLabels, createLabel, append, send` (exactly
today's gmailApiImap01 op names).

Response shape is whatever the current n8n leaf workflows already produce — **do not redesign
payloads in this step.** This refactor moves ownership, not schemas.

## 4. n8n (step 4)

`driveApi01` / `gmailApiRouter01` collapse to: one HTTP Request node ->
`http://drive:8975/<op>` / `http://mail:8970/<op>` with `{...params}`. Delete `const BACKEND`, the
Backend Switch, the google/oauth leaf branches, and the `substitute_backend` calls in
`scripts/n8n-push`. n8n holds NO Google credentials afterwards.

## 4b. Connect UX — a GUIDED FLOW, never a raw jump

**Users pick a PROVIDER, not a protocol.** "Google Drive", not `drive_google_oauth`. The provider is
the noun; the protocol is derived from (provider × auth method). The catalog must be provider-first:

```jsonc
provider: { id:"google_drive", name:"Google Drive", icon,
            auth_methods:[ {id:"oauth", label:"התחברות עם Google", protocol:"drive_google_oauth",
                            needs:[], recommended:true},
                           {id:"service_account", label:"חשבון שירות", protocol:"drive_google_sa",
                            needs:["json_key"], help_url} ] }
```
One provider may offer several auth methods; each maps to exactly one protocol. `local` is a
first-class provider, listed first, never hidden as a fallback.

**The flow — every step visible, reversible, and resolving to a state:**
1. **Provider** — cards. What it is, not how it authenticates.
2. **How to connect** — the provider's auth methods, each explaining what it needs and what it will
   be able to do. Recommended one marked.
3. **Provide** — OAuth: explain what happens, then hand off and show an explicit *waiting for
   consent* state (the window may be closed / may fail — say so). Key/password: a form with help
   text + a link to where the value comes from.
4. **Verify** — run the adapter probe and SHOW the result. A connection is never "added"; it is
   **verified**. Failure names what to fix.
5. **Name + activate** — label it, optionally make it active. Done.

**State propagation is the whole point.** Every connection row carries a live state chip
(`מחובר` / `בבדיקה` / `דורש טיפול` / `שגיאה`) + last-checked + the service's own reason. Writes are
pending → confirmed-by-probe, never optimistic. Errors say what to do next, never a stack trace.

⚠ ANTI-PATTERN (what we shipped and must replace): "חבר חשבון חדש" → straight to an authorize_url.
No provider choice, no protocol choice, no explanation, no waiting state, no verification. It is
the same shape as the console→connections 404 bug, where a primary CTA silently did nothing — a
flow with a required visible state per step cannot fail silently.

Design rules stand: RTL Hebrew, console/my-docs language, Lucide icons (never emoji), fits any
screen size, no dead ends.

## 4c. Extension points — how INDOX gets its sync UI back

Invariant (b) says a platform service knows nothing about sync. It does NOT say the sync UI dies —
it says the service must not **own** it. Platform services are **extendable**: an app registers UI
extensions, the platform renders them in slots and never interprets them.

**PRESERVE THIS — the current drive UI (to be re-injected by INDOX, not deleted).** As shipped
today at `/a/drive`, sync-shaped and therefore in the wrong layer, but the UX is right:
- A right-hand rail per sync entry (`drive-bs`, `drive-gdoc`, `drive-gdoc 2`, `drive-gdoc 3`) —
  i.e. one group per `sync_registry` entry.
- Each group lists its four state containers: `סנכרון` (to_sync) · `בתהליך` (in_progress) ·
  `סונכרן` (synced) · `כשל` (failed) — the folder-pair 4-tuple, made visible.
- **Drag-and-drop onto a sync folder** to enqueue work ("בחר תיקייה, או גרור קבצים לתיקיית סנכרון"),
  plus an "העלאת מסמכים" action.
- Live counts per state = interactive observability: you SEE the pipeline move.

**Slots the services must expose** (generic, app-agnostic — `chat`/`bank` get them free):
```jsonc
GET /extensions            -> registered extensions (app, slot, spec)
POST /extensions           -> an app registers: {app, slot, spec}
```
- `slot: "rail"` — a side panel (this is where INDOX's sync groups live)
- `slot: "container_badge"` — a badge/count on a folder/label
- `slot: "item_action"` — an action on a file/message
- `slot: "dropzone"` — a container declared as a drop target; the drop POSTs to the APP's callback

The platform renders a rail/badge it was handed; it never learns what `BS_TO_SYNC` means. INDOX
registers the rail above from `sync_registry`, and the drop callback is INDOX's, not drive's.

Order: build the domain-native core first (folders/files), then the slots, then move today's rail
into INDOX as the first extension. Do NOT delete the current UI until INDOX can re-inject it —
losing the drag-and-drop observability would be a real regression.

## 5. Invariants

**a. Credentials never cross into n8n or into the orchestration layer — only ops and readiness do.**
Every bug of 2026-07-16 (#8 missing N8N_OWNER_*, #9 Secure cookie over internal http) is a
credential crossing that line.

**b. A platform service knows NOTHING about sync, INDOX, or any app above it.**
Dependencies point one way: INDOX → drive/mail, never back. The moment the drive UI knows what
`BS_TO_SYNC` means, drive cannot ship without INDOX and the next app inherits INDOX's vocabulary.

The UI is **domain-native, not sync-shaped**:
- `drive` = folder tree · file list · preview · upload · move · trash · search. Like a drive.
- `mail`  = message list · thread · labels · search · compose. Like a mail client.

**Sync tags need no feature.** They are not special: they ARE folders and labels. A correct mail
view lists labels, so `BS_TO_SYNC` renders for the same reason `Inbox` does — the UI never learns
why it exists. Nothing to build; something to NOT build.

FORBIDDEN in a platform service (code, UI, or queries): the `incoming_documents` / `sync_ledger` /
`sync_registry` tables, `SOURCE_LINK` joins, INDOX status vocabulary, anything named `*sync*`.
⚠ `mailview` violates this today — it is an INDOX triage console (it joins mail to documents via
SOURCE_LINK). It is an INDOX app that happens to show mail; it is NOT the `mail` service's UI, and
must not be merged into it.

**Optional, only if a real need appears:** a generic display-only *annotations* registry — any app
publishes `{container_or_label → {badge, colour}}`; the platform renders the badge and never
interprets it. Generic in both directions, so `chat`/`bank` get it free. Do not build it
speculatively; plain labels and folders are already sufficient.
