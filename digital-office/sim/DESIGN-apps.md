# Drive · Mail · Chat — system + UI design (digital-office)

Goal: three best-in-class, Hebrew-native, fully-covering apps over ONE abstracted provider layer, with
perfect navigation between apps and between connected instances. Local-first; any provider can plug in.

---

## 1. System — the abstracted provider layer

One contract, three services (drive / mail / chat). Every app is a thin, provider-agnostic UI over it;
each provider is an adapter. In the sim this lives in `sim/instances.js` (the abstraction + a shared
switcher) and each app's mock implements the adapter; for the live platform it's a per-service
"connections" API + a front-end `<InstanceSwitcher>` component.

**Instance contract (identical across services):**
```
GET    connections            → { instances:[{id, provider, label, identity, color, status, builtin}], active }
POST   connections/select     { id }
POST   connections            { provider, … }        → { id }         (connect / add)
DELETE connections/{id}                                                (remove; never the built-in local)
GET    providers              → [{ provider, name, icon, description, auth_methods:[…] }]
```
- **local-first**: a built-in `local` instance is always present and active by default; never removable.
- `provider` → brand icon + color. `identity` = email / handle / "מקומי · מובנה".
- switching `active` swaps the service's data plane; an **"all"** pseudo-instance aggregates across instances.

**Service data planes (provider-agnostic verbs):**
| Service | Objects | Core verbs |
|---|---|---|
| drive | folders, files | list, open, preview, upload, move, rename, copy, star, trash, restore, delete, search |
| mail | folders/labels, threads, messages, drafts | list, open, compose, reply/forward, star, label, archive, snooze, mark, trash, search |
| chat | conversations, messages | list, open, send, attach, mark-read, pin, mute, search |

Provider registries: drive = Local · Google Drive · Dropbox · OneDrive · S3; mail = Local · Gmail ·
Outlook/Microsoft · IMAP; chat = Local · WhatsApp · Telegram.

---

## 2. Navigation model

- **App plane** — console left nav (Drive / Mail / Chat / …). Route `#/m/<app>`.
- **Instance plane** — the switcher at the top of each app: active instance chip → dropdown (active on
  top, other instances below, "add / connect", "manage"). Plus an **"All"** aggregate entry.
- **Object plane** — inside an instance: folder/label/conversation nav → item → detail.
- Deep-link: `#/m/<app>/<instance>/<path>` so cross-app "open in Drive/Mail" lands on the exact item.
- The switcher, connect flow, and empty/error/loading states are IDENTICAL across the three apps.

---

## 3. Per-app UI — full feature set (the "fully covering" bar)

### Drive (file-explorer complete + cloud-drive complete)
- Left: instance switcher · New (▾ folder / upload / Doc / Sheet / Slides) · quick views **Recent /
  Starred / Shared / Trash** · storage meter · folder tree.
- Top: breadcrumbs · search + filters (type/owner/modified) · **list⇄grid** toggle · sort · view density.
- Center: file rows/cards with **true type icons** (Docs blue / Sheets green / Slides yellow / PDF red /
  image / folder / archive / generic), owner, modified, size; multi-select (click/shift/ctrl/⌘A),
  drag-to-folder, drag-drop upload with progress.
- Right: details/preview pane (thumbnail, metadata, activity).
- Context menu: open · open-with · download · rename · move · copy · make-a-copy · star · share · details · trash.
- States: empty folder, no-results, uploading, offline-instance.

### Mail (Gmail complete, multi-account)
- Left: instance switcher + **All inboxes** · Compose · folders/labels (Inbox/Starred/Snoozed/Sent/
  Drafts/Trash + custom, per-account color) · storage.
- Top: search + operators · select-all · refresh · density.
- Center: thread list — avatar, sender, subject, snippet, date, attachment/star, unread bold, per-account
  color stripe; row hover actions (archive/snooze/delete/mark); bulk bar.
- Right/overlay: reader (thread collapse, attachments, reply/reply-all/forward) · **compose** modal.
- All-inboxes = merged, per-account-tagged view.

### Chat (WhatsApp/Telegram-class, multi-provider)  ← biggest new build
- Left: instance switcher (Local / WhatsApp / Telegram) + **All chats** · search · conversation list
  (avatar, name, last-message preview, time, unread badge, pin/mute).
- Center: thread — header (name, presence, actions) · message groups by sender · bubbles with time +
  delivery ticks · date separators · media/attachments · system messages.
- Footer: composer (attach, text, emoji, send) · voice affordance.
- Right (optional): contact/info panel.
- States: no-conversation-selected, empty, disconnected-provider (QR connect for WhatsApp).

---

## 4. Build phases (sim-only, each QA'd + delivered)

1. **Abstraction + unified switcher** — `sim/instances.js` + `sim/enhance/switcher.js`; apply to Drive
   (replaces native bar) and Mail (new). Mail de-INDOX + accounts + **All inboxes**. ← next
2. **Drive full UI** — grid/list, true type icons, breadcrumbs, details pane, quick views, richer menu.
3. **Mail full UI** — compose, reader polish, per-account color, unified inbox, labels.
4. **Chat full client** — conversation list + thread + composer, multi-provider, over the same contract.
5. **Navigation + polish** — deep-links, All-aggregates, empty/error/loading states, fresh ui-map + QA.

Drive foundation (local-first multi-provider, de-INDOX, connect flow) is already done (Phase 0).
Everything tracked in `ALIGNMENT-CHANGELOG.md` / `CONNECTED-INSTANCES.md` for the live port.
