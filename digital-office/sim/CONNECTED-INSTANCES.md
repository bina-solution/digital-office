# Connected instances — one switching pattern for Drive, Mail & Chat

The digital-office is a **hub over many providers**. Drive, Mail, Chat and INDOX each aggregate a set of
**connected instances**: a built-in **local** instance that's always present, plus external provider
instances the user connects (Google Drive / Dropbox / OneDrive…; Gmail / Outlook / IMAP…; WhatsApp /
Telegram…). The user switches between instances and interacts with all of them from inside the platform.

This doc defines the ONE pattern all three apps use, so they feel identical.

## The model (per app)

```
instances: [
  { id, provider, label, email|handle, account_hint, color, status, builtin? }, …
]
active: <id>            # exactly one active at a time
```
- **local-first**: the built-in local instance is the home/default active instance. It is never removable.
- switching `active` swaps what the app shows (that instance's files / mailbox / conversations).
- each instance carries a `provider` (→ icon + brand color) and an identity hint (email / handle / “מקומי · מובנה”).

Provider registries per app:
| App | Local (built-in) | External providers |
|---|---|---|
| **Drive** | אחסון מקומי | Google Drive, Dropbox, OneDrive, S3/תואם |
| **Mail** | דואר מקומי | Gmail, Outlook/Microsoft, IMAP |
| **Chat** | צ׳אט מקומי | WhatsApp, Telegram, (future) |

## The switcher UI (Google-style, Hebrew RTL)

**Placement (updated by C15):** the chip lives in the **console's own top bar** (`.topbar .tb-right`,
as the last child = the far end of the line, which in RTL is screen-left — where Gmail and Drive keep
the account). It used to sit in `#acctBar`, a full-width band between the console header and the app
frame; that band cost every app ~56px of height to hold one chip and is now collapsed. The app's own
account slot (`#acct` in דרייב, `#acctBox` in מייל) stays hidden — there is exactly ONE switcher.

Closed state = a chip: provider avatar (colored initial) + active instance label + identity hint +
status dot + chevron. It degrades by width — identity line under 1100px, label under 760px, leaving
avatar + status. **Only the chip degrades**: the open menu keeps every label at every width, because
a list of identical coloured circles is not a compact switcher.

Open state (dropdown):
1. **Active instance** at top — larger avatar, label, identity hint, "מחובר/status".
2. **Other connected instances** below, on a subtle grey ground — each a row (avatar + label + hint),
   click to switch; a remove (🗑 → trash icon) on non-builtin instances.
3. **Footer action** "חיבור חשבון/מקור חדש" → the full **connect flow**.

## The connect flow (full, shared 5 steps)

`ספק → אופן החיבור → אישור → בדיקה → הפעלה`
1. **Provider** — grid of provider cards (icon, name, description; the built-in local is marked מובנה).
2. **Method** — the provider's auth methods (OAuth / API-key form / built-in).
3. **Consent** — OAuth opens a consent window (sim: a `sim-oauth:<provider>` `window.open` hook
   provisions the instance offline after a short delay; the app polls the instance list and picks it up).
   Key-based methods show a `needs[]` field form.
4. **Verify** — probe the new instance.
5. **Activate** — set it active.

## Where it lives in the sim (sim-only)

- **Drive** (`localdrive`): the real app already ships this exact switcher (`#acctBtn`/`#acctMenu`) and the
  5-step wizard. The mock (`mocks/localdrive.js`) now serves a local-first, multi-provider instance list
  (`ACCOUNTS`), per-instance content (`DRIVE[id]`), and the connect endpoints. **Done.**
- **Mail** (`mailview`): the real app has NO switcher (single hardwired account). Add it via a sim
  enhancement overlay (`sim/enhance/mailview.js`) that injects the same switcher into the `#acctBox`
  slot + drives an `accounts`/`account/select` mock, plus an **"All inboxes"** unified view. **Next.**
- **Chat** (`wadmin`): generalize to local + WhatsApp + Telegram… same switcher + connect flow. **Later.**

For the live platform, this becomes a shared front-end component + a per-service "connections" API with
a local floor and pluggable providers — tracked here so Drive/Mail/Chat port to one implementation.
