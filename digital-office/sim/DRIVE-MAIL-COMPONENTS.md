# Drive & Mail — what the billion-user products actually know

For each component: **Serves** (the user job) · **Interaction** (the precise designed behaviour) ·
**Learned** (the insight from years and billions of users — usually why the obvious alternative loses).

Primary references: **Gmail** and **Google Drive**. Outlook and Dropbox are cited where they differ and
the difference is genuinely better. Open-source clients (Nextcloud Files, Roundcube, Thunderbird) are
consulted for architecture and component *scale* only, never as the visual target.

Status: **✓** have · **~** partial · **✗** missing. Priority: **P0** = in the first two seconds ·
**P1** = first interaction · **P2** = depth.

---

# PART A · MAIL

## A0 · The opening frame, and why ours read as an internal tool

Gmail opens as: search across the top · a left rail whose first element is a large Compose pill · then
**rows**, each `checkbox · star · importance · sender · subject — snippet · date`, unread white and
bold against a tinted ground for read.

Ours opened as a **`<table>` with column headers** (סטטוס | מאת | נושא | תאריך). That is the single
loudest signal of "admin tool". A table says *these are records you will sort and compare*. A mail list
says *these are messages you will triage*. Gmail abandoned the table because triage is a per-row
decision — you never sort your inbox by sender to compare rows; you scan top-down and act.

Second: **density**. Gmail rows are ~40px; ours were table cells with generous padding, so roughly 40%
less mail fit on screen. Density is not cosmetic — it determines how much of your inbox you can hold in
working memory at once.

Third: **inertness**. Gmail's row swaps the date for four actions on hover. Ours had no hover state, so
nothing suggested a row was actionable.

---

## Global chrome

### A1 · Search field (wide, rounded, top)
- **Serves** — for mailboxes past a few thousand messages, search overtakes folders as the primary
  retrieval method.
- **Interaction** — always visible, spans the content width; focusing expands it and drops a suggestion
  panel; Enter searches, Esc restores.
- **Learned** — Gmail bet the product on "search, don't sort" and made the field enormous to teach it.
  The width *is* the instruction. A small search box next to a title trains folder-first behaviour.
- Ours: ~ small box · **P0**

### A2 · Search chips (From · Any time · Has attachment · To · Unread)
- **Serves** — filtering without learning `from: has:attachment` grammar.
- **Interaction** — appear under the field on focus; each opens a small popover; selections become
  removable chips that compose with each other; the raw query stays editable underneath.
- **Learned** — Gmail had the query grammar for a decade and most users never used it. Chips were added
  because **discoverable filtering beats powerful filtering**. The grammar stayed for the minority.
- Ours: ✗ · **P1**

### A3 · Quick-settings drawer (density · theme · reading pane · inbox type)
- **Serves** — the handful of preferences that materially change the layout.
- **Interaction** — a gear opens a right drawer; every change applies **instantly and live**, no Save.
- **Learned** — Gmail moved these out of the full settings page because users could not find them.
  Instant apply exists because layout preferences are judged visually — a Save button forces a
  guess-then-check loop.
- Ours: ✗ · **P2**

### A4 · Density switch (Default / Comfortable / Compact)
- **Serves** — how much mail fits per screen.
- **Interaction** — three options changing row height and avatar visibility; nothing else moves.
- **Learned** — a genuine bimodal preference: high-volume users want compact, casual users want air.
  Google ships all three rather than picking, because the "right" density depends on mail volume, which
  varies by orders of magnitude across the user base.
- Ours: ✗ · **P1**

---

## Left rail

### A5 · Compose pill
- **Serves** — the app's one primary action.
- **Interaction** — largest, highest-contrast element in the rail, top-left, never scrolls away.
- **Learned** — it stayed oversized through every redesign because composing is the only action with no
  alternative entry point. Everything else in mail is reactive.
- Ours: ✓

### A6 · System labels (Inbox · Starred · Snoozed · Sent · Drafts · Important · Scheduled · All Mail · Spam · Trash)
- **Serves** — the mental model of *where mail can be*. Without it the user cannot answer "where did
  that go?" after any action.
- **Interaction** — fixed order, Inbox first and bold; the current one is highlighted; counts to the
  right; the tail collapses behind More.
- **Learned** — the order is not alphabetical or configurable: it is **frequency-ordered from a billion
  sessions**. Snoozed sits third because snoozing creates anxiety about where the message went.
- Ours: ✗ (only "all mail") · **P0** — this is the biggest structural gap in our mail rail.

### A7 · Unread counts
- **Serves** — triage priority at a glance.
- **Interaction** — bold count when unread; **absent, not zero**, when empty.
- **Learned** — showing `(0)` was tested and removed: a zero is visual noise that reads as a badge.
  Absence is the cleaner signal for "nothing to do".
- Ours: ~ · **P0**

### A8 · More/Less expander
- **Serves** — keeps ~6 items visible instead of 14.
- **Interaction** — one row that expands in place, remembered across sessions.
- **Learned** — most users touch four labels. The rest must exist but must not cost vertical space,
  because vertical space in the rail competes with custom labels, which are what power users care about.
- Ours: ✗ · **P1**

### A9 · Custom labels with colour dots
- **Serves** — the user's own taxonomy.
- **Interaction** — below system labels; a colour dot; hover reveals ⋮ (colour, rename, nest, remove).
- **Learned** — colour is the retrieval key, not the name — people scan the rail by colour. Gmail
  offers a fixed palette rather than a picker because arbitrary colours produce unreadable contrast.
- Ours: ~ flat list · **P1**

### A10 · Storage meter
- **Serves** — quota awareness before hitting the wall.
- **Interaction** — a thin bar at the rail's bottom, and the upsell only appears past ~75%.
- **Learned** — bottom placement is deliberate: it must be *findable* when you think about storage and
  *invisible* the rest of the time.
- Ours: ✗ · **P2**

---

## List toolbar

### A11 · Select-all checkbox **with dropdown** (All · None · Read · Unread · Starred · Unstarred)
- **Serves** — bulk triage, which is how anyone with real volume actually works.
- **Interaction** — the box selects/clears the page; the caret opens predicate selection; selecting
  everything on the page offers "select all N conversations that match".
- **Learned** — the predicates exist because the real bulk job is never "these 50" — it is "every
  unread promotion". A plain select-all forces manual deselection, which is slower than not bulk-acting.
- Ours: ~ plain checkbox · **P0**

### A12 · Bulk action bar (Archive · Spam · Delete · Mark read · Snooze · Move · Labels)
- **Serves** — acting on the selection.
- **Interaction** — **replaces** the idle toolbar in place rather than appearing elsewhere; icon-first
  with tooltips; disappears when the selection clears.
- **Learned** — replacing in place keeps the actions where the eye already is. A separate bar appearing
  below or above costs a re-fixation and was measurably slower.
- Ours: ~ 4 actions · **P0**

### A13 · Pagination `1–50 of 1,234`
- **Serves** — position and scale in a large mailbox.
- **Interaction** — right-aligned; arrows page; the count is exact for small mailboxes and approximate
  ("many") for huge ones.
- **Learned** — Gmail paginates rather than infinite-scrolls the inbox because triage is a bounded
  task: a page is a finishable unit of work. Infinite scroll removes the sense of completion.
- Ours: ~ count only · **P1**

### A14 · Category tabs (Primary / Promotions / Social / Updates)
- **Serves** — separating mail-you-answer from mail-that-arrives.
- **Interaction** — tabs above the list; drag a message to a tab to retrain it.
- **Learned** — the single largest reduction in perceived inbox volume Gmail ever shipped. Note the
  design honesty: it *hides nothing* — every tab is one click away — because filtering that hides mail
  destroys trust the first time something important is missed.
- Ours: ✗ · **P2** (Outlook's Focused/Other is arguably better for business mail)

---

## The row — the component that matters most

### A15 · Checkbox
- **Serves** — selection.
- **Interaction** — leading edge, generous hit area, click never opens the message.
- **Learned** — it is always visible, not hover-revealed. Hover-revealed checkboxes were tried and
  failed: users could not find how to multi-select, and on touch there is no hover at all.
- Ours: ✓ new · **P0**

### A16 · Star
- **Serves** — the lightest possible "come back to this".
- **Interaction** — one click on/off, amber when set, no confirmation, instantly reversible.
- **Learned** — starring survived every redesign because **zero-cost, zero-consequence marking** is the
  only flagging users actually adopt. Every heavier scheme (priorities, folders-on-flag) was abandoned.
- Ours: ✓ new · **P0**

### A17 · Importance marker (chevron)
- **Serves** — the system's own guess at priority, and a training signal back to it.
- **Interaction** — a small chevron beside the star; clicking corrects the classifier.
- **Learned** — kept deliberately visually quieter than the star: the *user's* signal must outrank the
  *machine's*. When the machine's marker looked equally loud, users distrusted the whole row.
- Ours: ✓ new · **P1**

### A18 · Sender column (fixed width)
- **Serves** — scanning by who, which is how people actually locate mail.
- **Interaction** — fixed ~168px so senders form a clean scannable column; thread senders collapse to
  "A, B, C 3".
- **Learned** — the fixed width is the point. Proportional sender columns produce a ragged left edge
  that destroys vertical scanning — the exact failure of a generic data table.
- Ours: ✓ new · **P0**

### A19 · Sender avatar
- **Serves** — pre-linguistic recognition; you know the sender before reading.
- **Interaction** — circular, colour derived deterministically from the name, initial as fallback.
- **Learned** — deterministic colour matters more than accuracy: the *same* sender must always be the
  same colour, or the recognition shortcut breaks.
- Ours: ✓ new · **P1**

### A20 · Subject + **inline snippet**
- **Serves** — deciding whether to open, without opening.
- **Interaction** — subject then a muted em-dash snippet on the *same line*, both truncated together.
- **Learned** — Gmail tested a two-line row (subject over snippet) and reverted: one line per message
  nearly doubles messages per screen, and the snippet is only a tiebreaker, not primary content.
- Ours: ✓ new · **P0**

### A21 · Read/unread ground
- **Serves** — the list's fundamental rhythm — what have I dealt with.
- **Interaction** — unread: white + bold sender/subject/date. Read: tinted ground, regular weight.
- **Learned** — encoded **twice** (weight *and* background) on purpose. Weight alone fails for users
  with low-contrast displays or reduced vision; background alone is too subtle at a glance.
- Ours: ✓ new · **P0**

### A22 · Hover actions replacing the date
- **Serves** — triage in one gesture, no menu, no selection.
- **Interaction** — hovering swaps the date for archive · delete · mark read · snooze, in the same slot.
- **Learned** — reusing the date's slot is the trick: no layout shift, no extra width, and the actions
  appear exactly where the pointer already travelled. Actions in a fixed trailing column were tried and
  cost horizontal space on every row for something used on a minority of rows.
- Ours: ✓ new · **P0**

### A23 · Archive as the default action
- **Serves** — clearing the inbox without deciding where things go.
- **Interaction** — archive is first, leftmost, most reachable; delete is deliberately *second*.
- **Learned** — the single most important idea in modern mail: **storage is cheap, decisions are
  expensive**. Archive removes the message from view without asking the user to file or destroy it.
  Ordering archive before delete measurably reduces regret.
- Ours: ✓ new · **P0**

### A24 · Snooze
- **Serves** — mail that is not actionable *yet*.
- **Interaction** — hides until a chosen time, then returns to the top of the inbox as unread.
- **Learned** — invented because users were emailing themselves reminders and marking things unread as
  a to-do hack. Snooze is the productised version of a workaround observed at scale.
- Ours: ✓ new (mechanism) · **P1** (needs a time picker)

### A25 · Thread collapse with participant count
- **Serves** — one conversation is one row regardless of message count.
- **Interaction** — newest message wins the row; a count shows depth; expanding reveals the messages.
- **Learned** — conversation view was Gmail's founding differentiator. Per-message rows meant a
  ten-reply thread consumed ten rows of a fifty-row screen.
- Ours: ✓

### A26 · Right-click context menu on a row
- **Serves** — the full action set without leaving the row.
- **Interaction** — native-feeling menu with the same verbs as the toolbar.
- **Learned** — added late, because users kept right-clicking expecting it. Shipping it acknowledged
  that a web app in a desktop window inherits desktop expectations.
- Ours: ✗ · **P2**

### A27 · Loading skeletons
- **Serves** — perceived speed.
- **Interaction** — grey row placeholders in the final layout, not a spinner.
- **Learned** — skeletons matching the final geometry reduce *perceived* latency even when actual
  latency is unchanged, because the eye can pre-position.
- Ours: ✗ · **P1**

---

## Conversation view

### A28 · Message header (avatar · name `<email>` · to-line expander · date)
- **Serves** — provenance; "who is this really from, and who else got it".
- **Interaction** — the to-line collapses to "to me" with a caret revealing full recipients.
- **Learned** — the collapsed to-line is a phishing defence as much as a space saving: the full header
  must be one click away, never hidden.
- Ours: ~ · **P1**

### A29 · Quoted-text collapse (`…`)
- **Serves** — hiding the reply chain that repeats in every message.
- **Interaction** — a small `…` button expanding the trimmed content in place.
- **Learned** — without it, a long thread renders the same text N times. The collapse is heuristic and
  therefore always reversible — a wrong trim must never lose content.
- Ours: ✗ · **P2**

### A30 · Attachment cards
- **Serves** — the payload people actually came for.
- **Interaction** — thumbnail cards below the body, with download and "save to Drive" on hover.
- **Learned** — promoted from a filename link to a preview card because attachments are the highest-
  intent object in business mail. Save-to-Drive exists because the next step is nearly always "keep it".
- Ours: ~ · **P1**

### A31 · Reply / Reply all / Forward
- **Serves** — the response loop.
- **Interaction** — buttons at the *end* of the last message, where reading finishes.
- **Learned** — placement at the end beats a top toolbar because the decision to reply is made after
  reading, not before.
- Ours: ✓

### A32 · Inline reply composer
- **Serves** — replying without a separate window.
- **Interaction** — clicking Reply expands an editor inside the thread, keeping context visible.
- **Learned** — replacing the pop-out for replies raised reply rates: seeing what you are answering
  while answering it is worth more than window independence.
- Ours: ✗ · **P2**

---

## Compose

### A33 · Floating bottom-right window
- **Serves** — writing without losing the list.
- **Interaction** — anchored bottom-right, non-modal; the list stays live behind it.
- **Learned** — the famous change from full-page compose. Non-modal composing means you can look
  something up mid-draft, which is the single most common compose interruption.
- Ours: ✓

### A34 · Minimise / pop-out / full-screen
- **Serves** — long drafts and multi-drafting.
- **Interaction** — three window controls; minimised drafts stack along the bottom edge.
- **Learned** — the stack exists because people genuinely keep several drafts open; a single compose
  slot forced draft-saving as a workaround.
- Ours: ✗ · **P1**

### A35 · Recipient chips
- **Serves** — unambiguous addressing.
- **Interaction** — a resolved address becomes a chip with avatar; invalid ones stay red text; chips
  are removable and draggable between To/Cc/Bcc.
- **Learned** — chips make "did it resolve?" answerable at a glance. Free-text recipients produce
  silent typo-sends, the least recoverable error in mail.
- Ours: ~ plain text · **P1**

### A36 · Autosave indicator
- **Serves** — trust that nothing is lost.
- **Interaction** — a quiet "Draft saved" that appears and fades.
- **Learned** — must be visible but never demand attention; drafts save constantly and a loud
  indicator becomes flicker.
- Ours: ✗ · **P1**

### A37 · Schedule send
- **Serves** — writing now, delivering later.
- **Interaction** — a split button beside Send with presets plus a custom picker.
- **Learned** — a split button, not a menu item: the default action must stay one click while the
  variant stays discoverable.
- Ours: ~ · **P2**

---

## System feedback

### A38 · **Undo snackbar** ("Conversation archived · Undo")
- **Serves** — making destructive actions safe.
- **Interaction** — bottom-left toast, ~5s, with an Undo affordance; stacks are collapsed to the latest.
- **Learned** — **the most important single lesson in this entire document.** Gmail replaced
  "are you sure?" dialogs with act-then-undo. Confirmation dialogs tax the 99% of correct actions to
  protect the 1% wrong one; undo taxes nothing and protects everything. Undo Send is the same idea
  applied to the highest-regret action in the product.
- Ours: ✗ · **P0**

### A39 · Keyboard shortcuts (`j/k`, `e`, `#`, `r`, `?`)
- **Serves** — power throughput.
- **Interaction** — off by default, opt-in in settings; `?` shows the map.
- **Learned** — off by default because single-letter shortcuts destroy the experience for anyone who
  doesn't know them. The `?` overlay is the discovery path.
- Ours: ✗ · **P2**

### A40 · Empty state
- **Serves** — an honest zero, and a reward.
- **Interaction** — illustration plus a line of text; Gmail celebrates inbox zero.
- **Learned** — the celebration is deliberate: finishing triage is the product's success condition, and
  marking it reinforces the archive-don't-file behaviour the whole design encourages.
- Ours: ✓

---

# PART B · DRIVE

## B0 · The opening frame

Drive opens as: wide search · a rail whose first element is a big **`+ New`** · **filter chips** under a
**breadcrumb** · then a white rounded container holding either a **grid of thumbnail cards** or a
**list with sortable headers**, with **list/grid** and **ⓘ details** toggles at its top-right.

Ours opened as: a title, a folder-scoped search, a drop-zone banner, and a three-column table with one
file. No chips, no breadcrumb, no view toggle, no thumbnails, no hover actions, no details pane — and
no sense of a file system, because the rail listed only "my folders".

---

## Global chrome

### B1 · Filter chips (Type · People · Modified · Location)
- **Serves** — narrowing without syntax; the modern Drive signature.
- **Interaction** — always visible under the header; each opens a popover; selections become removable
  chips that compose; they persist as you navigate.
- **Learned** — Drive's search was strong and unused. Chips converted search from a *recall* task
  ("what do I type?") into a *recognition* task ("pick from these"). Recognition beats recall at scale.
- Ours: ✗ · **P0**

### B2 · Search scope
- **Serves** — finding across the whole drive, not just here.
- **Interaction** — searches everything by default; a Location chip narrows to the current folder.
- **Learned** — folder-scoped-by-default search was the wrong default: users search precisely when they
  *don't* know which folder it is in.
- Ours: ~ folder-scoped · **P0**

---

## Left rail

### B3 · `+ New` button with menu
- **Serves** — every creation path in one place (folder · file upload · folder upload · Docs/Sheets/Slides).
- **Interaction** — a large button, visually distinct from the nav below it, opening a menu.
- **Learned** — one create entry beats scattered per-type buttons: users learn *one* place to start,
  and new file types can be added without redesigning the rail.
- Ours: ~ upload only · **P0**

### B4 · My Drive with an expandable tree
- **Serves** — the spatial model. People remember *where* files are.
- **Interaction** — disclosure triangles expanding in place; the current folder is highlighted; the
  tree is a drop target for filing by drag.
- **Learned** — Drive kept the tree despite pushing search because spatial memory is the strongest
  retrieval cue people have for their own files. Removing it in early redesigns caused measurable loss.
- Ours: ~ flat · **P0**

### B5 · Shared with me
- **Serves** — the collaboration inbox: things others put in front of you.
- **Interaction** — a separate root, sorted by *share date* not modified date.
- **Learned** — it is a distinct root because shared files have no location in *your* hierarchy. This
  is the concept that made cloud storage social rather than personal.
- Ours: ✗ · **P0**

### B6 · Recent
- **Serves** — resuming work, which is the most common Drive session.
- **Interaction** — flat, time-ordered, grouped Today / Yesterday / Last 7 days / Earlier.
- **Learned** — for the "I was just working on this" case, recency beats any hierarchy. This view
  quietly absorbs a large share of all navigation.
- Ours: ✗ · **P0**

### B7 · Starred
- **Serves** — the user's own shortlist across all folders.
- **Interaction** — one click on any item; a cross-folder virtual view.
- **Learned** — same lesson as mail's star: the cheapest possible marking is the only one adopted.
- Ours: ✗ · **P0**

### B8 · Trash with retention
- **Serves** — recovery.
- **Interaction** — deleted items stay ~30 days with the countdown shown; Empty trash is explicit.
- **Learned** — the visible countdown converts "deleted" from terrifying to reversible, which is what
  lets the product avoid a confirmation dialog on every delete.
- Ours: ✓

### B9 · Storage meter
- **Serves** — quota awareness.
- **Interaction** — bar plus used/total; upsell only near the limit.
- **Learned** — storage is the monetisation surface, so its restraint is notable: pushing it constantly
  measurably reduced trust.
- Ours: ✗ · **P1**

---

## Content header

### B10 · Breadcrumb with per-crumb dropdowns
- **Serves** — where am I, and jump anywhere up the chain.
- **Interaction** — `My Drive › Clients › 2026`; each crumb is a link *and* a dropdown of its siblings;
  long paths collapse in the middle.
- **Learned** — the per-crumb dropdown converts the breadcrumb from a passive indicator into a
  navigator, removing most "go up, then down again" round-trips.
- Ours: ✗ · **P0**

### B11 · List / grid toggle
- **Serves** — two genuinely different reading modes.
- **Interaction** — a paired icon toggle; the choice persists per user.
- **Learned** — not a preference so much as a *content* switch: grid wins for images and decks
  (recognition by thumbnail), list wins for documents (comparison by name/date/size). Both must exist
  because a real drive contains both.
- Ours: ✗ · **P0**

### B12 · ⓘ details toggle
- **Serves** — metadata without leaving the list.
- **Interaction** — toggles a right pane that follows the selection; sticky across selections.
- **Learned** — a pane rather than a dialog because metadata is consulted *while* browsing. A modal
  forces open/close per file and kills the comparison flow.
- Ours: ✗ · **P0**

### B13 · Sortable column headers (Name · Owner · Modified · Size)
- **Serves** — ordering; "what's newest", "what's huge".
- **Interaction** — click to sort, click again to reverse, arrow shows direction; folders stay above files.
- **Learned** — folders-always-first survives every sort. Users think of folders as *places* and files
  as *things*, and interleaving them by date breaks the spatial model.
- Ours: ~ · **P0**

---

## Items

### B14 · Grid card with thumbnail
- **Serves** — recognising a file by appearance rather than name.
- **Interaction** — a rendered preview with a type-icon strip and name below; selection highlights the
  whole card.
- **Learned** — the thumbnail is the point. People name files badly, but recognise a document's shape
  instantly. This is why grid is the default for image-heavy folders.
- Ours: ✗ · **P0**

### B15 · Type-coloured icons
- **Serves** — instant type recognition.
- **Interaction** — Docs blue, Sheets green, Slides amber, PDF red, plus image/video/zip/folder.
- **Learned** — the colours are consistent across every Google surface, so the mapping is learned once
  and reused everywhere. Colour is read before shape and long before text.
- Ours: ✓ (overlay)

### B16 · Row hover actions (share · download · rename · ⋮)
- **Serves** — acting without a menu round-trip.
- **Interaction** — appear at the row's trailing edge on hover; ⋮ opens the full menu.
- **Learned** — the top three verbs are promoted out of the menu because they cover the large majority
  of actions. The menu remains for the tail.
- Ours: ✗ · **P0**

### B17 · Right-click context menu
- **Serves** — the complete verb set at the pointer.
- **Interaction** — Preview · Open with · Share · Get link · Move · Rename · Copy · Download · Remove.
- **Learned** — Drive's most-used power path. Ordering matters: Preview first because looking is more
  common than acting.
- Ours: ✗ · **P0**

### B18 · Multi-select (click · shift-range · ctrl-click · marquee)
- **Serves** — bulk work.
- **Interaction** — full desktop selection semantics, including dragging a marquee across empty space.
- **Learned** — Drive implements desktop file-manager semantics exactly because users arrive with
  Finder/Explorer muscle memory. Any deviation reads as broken.
- Ours: ~ · **P0**

### B19 · Bulk toolbar (`N selected` · share · download · move · trash)
- **Serves** — acting on many.
- **Interaction** — replaces the header in place; shows the count; Esc clears.
- **Learned** — same in-place replacement lesson as mail: keep actions where the eye already is.
- Ours: ✗ · **P0**

### B20 · Drag to a folder / drag into the page
- **Serves** — filing and uploading with the gesture people already know.
- **Interaction** — dragging over a folder highlights it; dragging into the page shows a full-surface
  drop overlay.
- **Learned** — the full-page drop target (rather than a small zone) exists because users aim at the
  window, not at a widget.
- Ours: ✓

### B21 · Upload progress card
- **Serves** — trust during long uploads.
- **Interaction** — bottom-right card, per-file rows with progress and cancel, collapsible, survives
  navigation.
- **Learned** — surviving navigation is the whole design: users start an upload and immediately go
  elsewhere. A progress bar bound to one screen loses the user's only feedback.
- Ours: ✗ · **P1**

### B22 · Shared / starred / offline badges
- **Serves** — state without opening.
- **Interaction** — small glyphs on the row/card; the shared badge shows an avatar stack.
- **Learned** — "who else can see this" must be answerable at the list level; asking users to open a
  dialog to check sharing caused real leaks.
- Ours: ✗ · **P1**

---

## Panels & dialogs

### B23 · Details pane
- **Serves** — the metadata answer: Type · Size · Location · Owner · Modified · Opened · Created · Description.
- **Interaction** — right pane following the selection, with a preview thumbnail at the top.
- **Learned** — **Location** is the most-used field, because the most common Drive question is "where
  does this actually live?" — a direct consequence of search-first navigation.
- Ours: ✗ · **P0**

### B24 · Activity pane
- **Serves** — who did what, when.
- **Interaction** — a second tab beside Details, reverse-chronological.
- **Learned** — separating Activity from Details is Drive's weakest split; **Nextcloud's tabbed right
  sidebar (Details / Sharing / Activity) is cleaner** and is the one place we prefer the open-source
  shape.
- Ours: ✗ · **P1**

### B25 · Sharing dialog
- **Serves** — the collaboration core.
- **Interaction** — people input with chips · per-person role (Viewer/Commenter/Editor) · notify +
  message · **General access** (Restricted vs Anyone with the link) · Copy link · advanced settings.
- **Learned** — the "Anyone with the link" control is deliberately separated from per-person access,
  because conflating them is exactly how documents leak. The separation is a safety design, not layout.
- Ours: ✗ · **P1**

### B26 · Preview overlay
- **Serves** — consuming a file without downloading it.
- **Interaction** — full-screen viewer, prev/next through the folder, zoom, print, download, open-with,
  info toggle; Esc closes.
- **Learned** — prev/next through the folder is what makes it a *viewer* rather than a preview: people
  review a batch of scans in sequence, and returning to the list between each is intolerable.
- Ours: ✗ · **P1**

### B27 · Move dialog with folder tree
- **Serves** — reorganising without dragging across a scroll.
- **Interaction** — a tree picker with a New folder button inside it.
- **Learned** — drag alone is insufficient once the destination is off-screen. The in-dialog New folder
  exists because "move it somewhere that doesn't exist yet" is common.
- Ours: ~ drag only · **P1**

### B28 · Empty states (folder · search · trash)
- **Serves** — guidance at the moment of nothing.
- **Interaction** — illustration + one action ("Drop files here or use New").
- **Learned** — each empty state names the *next action*, never just "no files". An empty folder is a
  teaching opportunity.
- Ours: ~ · **P1**

### B29 · Loading skeletons
- **Serves** — perceived speed.
- **Interaction** — grey card/row placeholders in the final geometry.
- **Learned** — same lesson as mail.
- Ours: ✗ · **P1**

### B30 · Suggested / Quick access
- **Serves** — resuming, predicted.
- **Interaction** — a row of cards above the folder contents with a reason ("You opened frequently").
- **Learned** — the *reason* string is essential; unexplained ML suggestions read as noise and get
  ignored. Explanation converts a guess into a recommendation.
- Ours: ✗ · **P1**

---

## Dropbox deltas worth taking

- **Sharing on the row, not behind a dialog** — link settings inline; fewer clicks to the most common task.
- **File requests** — collecting files from people without accounts. No Google equivalent.
- **Description/comments as a first-class right pane on every file** — better than Drive's afterthought.
- **Denser list with a clearer "shared with" avatar stack** than Drive's.

---

# PART C · The five ideas underneath all of it

1. **Undo, never confirm.** Confirmation taxes every correct action to protect the rare wrong one.
   Act immediately, offer undo. (Gmail archive/delete/send; Drive trash with retention.)
2. **Recognition over recall.** Chips instead of query syntax, thumbnails instead of filenames,
   colour instead of labels. Never make the user produce from memory what you can offer for selection.
3. **Cheap marking wins.** The star survived because it costs nothing and means nothing enforceable.
   Every heavier organisational scheme lost.
4. **Replace in place.** Bulk toolbars replace idle toolbars; hover actions replace the date. Keep the
   controls where the eye already is; avoid layout shift.
5. **Reduce decisions, not storage.** Archive exists so you needn't choose a folder. Search exists so
   you needn't maintain a hierarchy. The expensive resource is the user's judgement.

---

# PART D · Build order

**Wave 1 — the opening frame (P0).**
Mail: row anatomy + hover actions + read/unread ground *(done)* · full system-label rail with counts ·
select-all dropdown + full bulk bar · **undo snackbar**.
Drive: filter chips · breadcrumb · list/grid toggle · grid cards with thumbnails · row hover actions ·
right-click menu · real rail (Home / My Drive tree / Shared / Recent / Starred / Trash + storage) ·
details pane.

**Wave 2 — first interaction (P1).** Density switch · compose window controls · recipient chips ·
upload progress card · sharing dialog · preview overlay · skeletons · owner avatars · move dialog ·
badges · Suggested row.

**Wave 3 — depth (P2).** Category tabs · nested labels · quoted-text collapse · inline reply · smart
replies · version history · keyboard shortcuts · marquee select · activity pane.

---

# PART E · Overlays, full views, and using the screen properly

The three things that separate "a page that works" from "a product that feels right". Our current
Drive/Mail fail hardest here: open Drive and roughly **60% of the viewport is empty white** below a
three-column table holding one file.

## E1 · The overlay ladder — pick the lightest thing that works

Every product converges on the same five weights. Using a heavier one than the job needs is the most
common UI mistake, and it always reads as amateur.

| Weight | Use when | Dismiss | Examples |
|---|---|---|---|
| **Inline** (expand in place) | the change belongs in the flow | — | quoted-text `…`, folder tree expand |
| **Popover** (anchored, small) | a *choice* tied to a control | click-away, Esc | filter chips, role dropdown, label picker |
| **Menu** (anchored, list of verbs) | acting on a known target | click-away, Esc | right-click, row ⋮ |
| **Right pane** (non-modal, persistent) | information consulted *while* browsing | toggle | Drive details, Nextcloud sidebar |
| **Modal dialog** (centred, blocking) | a decision that must complete before anything else | Esc, ✕, backdrop | Share, Move, Rename |
| **Full-screen overlay** | consuming content | Esc | Drive preview |

**Learned:** the right pane exists precisely so metadata does *not* need a modal. A modal forces
open/close per file and destroys comparison. If a user might want it open across several items, it is
a pane, never a dialog.

## E2 · Modal rules (the ones everyone gets wrong)

1. **Anchor size to content, cap by viewport.** `width: min(560px, 92vw)`, `max-height: 88vh`, and the
   *body* scrolls — never the whole dialog. A dialog taller than the viewport with the primary button
   below the fold is the classic failure.
2. **Three zones, always.** Header (title + ✕) / scrollable body / footer with actions. The footer
   never scrolls away — the action must always be reachable.
3. **Primary action bottom-trailing**, secondary beside it, destructive separated.
4. **Esc closes, backdrop closes, focus is trapped, focus returns to the trigger.** All four, always.
5. **Never stack modals.** A modal opening a modal means the first one was the wrong weight.
6. **Open at the natural next state**, not empty — Move opens on the current folder's parent; Share
   opens with the input focused.
7. **No confirmation modals for reversible acts.** Use the undo snackbar instead (Part C, idea 1).

## E3 · Popovers

Anchored to their trigger with a ~8px offset, flipping when they'd overflow; width fits content
(min ~220px); close on click-away, Esc, or selection; **never trap focus** — they are lightweight by
definition. A popover that behaves like a modal is a modal wearing the wrong clothes.

## E4 · The full document view (Drive preview)

This is the component that makes a drive feel like a product.

- **Full-screen, black-ish backdrop.** The file is the only thing that matters now.
- **Chrome fades**: a top bar (name · ✕ · download · print · open-with · ⓘ) that dims after ~2s of no
  pointer movement and returns on move.
- **Prev/next through the containing folder** — the whole point. Reviewing a batch of scans without
  returning to the list between each is the actual job.
- **Fit-to-width by default**, with zoom controls and double-click to toggle fit/100%.
- **Esc closes and returns to the list with the item still selected and scrolled into view.**
- **The info pane opens *inside* the overlay**, not by closing it.
- **Learned:** losing your place on close is the failure that makes people avoid preview and download
  instead. Restoring scroll + selection is what makes the overlay feel free to enter.

## E5 · The full message view (Mail conversation)

- Full width of the content column, not a modal.
- Sticky action bar at the top (back · archive · delete · read · snooze · move · labels) so acting
  never requires scrolling back up.
- Long threads: earlier messages collapse to one-line summaries; the newest is expanded.
- Reply affordances at the **end**, where reading finishes.
- **Learned:** the back affordance must return to the exact list scroll position. Gmail treats the list
  position as state worth preserving because triage is a sequence, not isolated visits.

## E6 · Using the screen — the rules our apps break today

1. **One scroll region, not three.** The page must not scroll; the *list* scrolls inside a fixed
   shell. Header, rail and toolbar are fixed; only content moves.
2. **The content region fills the viewport.** `height: 100dvh` on the shell, `flex: 1; min-height: 0`
   on the list. Our Drive leaves ~60% empty because the container is content-sized instead of
   flex-filled — the single biggest "unfinished" signal in the app.
3. **Empty space must be *deliberate*.** An empty folder shows a centred empty state occupying the
   region — not a short table followed by void.
4. **Rail width is fixed, content is fluid.** ~256px rail, content takes the rest. Never split 50/50.
5. **Cap line length in reading contexts.** Message bodies max ~72ch, centred in their column.
   Full-width body text at 1600px is unreadable.
6. **Grid is responsive by `auto-fill`, not by breakpoint.** `repeat(auto-fill, minmax(180px, 1fr))`
   so cards reflow continuously instead of jumping at fixed widths.
7. **Sticky what you look back at**: list toolbar, table headers, dialog footers, breadcrumb.

## E7 · Sizing scale (what makes proportions feel "right")

Not arbitrary — these are the values the reference products converge on:

| Element | Value | Why |
|---|---|---|
| Rail width | 256px | fits the longest system label without truncation |
| Mail row height | 40–44px | ~1.6× the 13px type; below 36px hit targets fail |
| Touch target | ≥44px | the floor every platform agrees on |
| List type | 13px | dense but readable; 14px costs ~8% of rows per screen |
| Secondary type | 11–12px | metadata must lose to content |
| Grid card | 160–200px | a thumbnail recognisable at a glance without scrolling |
| Icon | 20px inline, 24px standalone | |
| Radius | 8px controls, 12–16px containers | |
| Row gap | 0 with a 1px divider | rows are a continuous surface, not separate cards |
| Modal | `min(560px, 92vw)` / `max-height: 88vh` | |
| Reading measure | ~72ch | the readability optimum |

**Learned:** the reason these products feel calm is that everything sits on one scale. Mixed spacing
(9px here, 14px there) is what makes an interface feel homemade even when every component is correct.


---

# PART F · What is built, and what deliberately is not

This study drove a rebuild of both forks (`sim/apps/mailview/`, `sim/apps/localdrive/`). This part
is the honest ledger: which of the components above now exist in the simulation, and — more useful —
which do not and **why that is the right call for this product**, not an oversight.

Ported-to-real notes live in `ALIGNMENT-CHANGELOG.md` **C11** (drive) and **C12** (mail).

## F1 · Mail — built

| Component (Part A) | Where |
|---|---|
| System-label rail, frequency-ordered, tail behind **עוד** | `SYS_VIEWS` · `renderSysNav()` |
| Unread counts, omitted at zero | `countFor()` |
| Places vs marks (archive/trash/snoozed vs starred/important) | `inView()` · `ARCHIVED`/`TRASHED`/`SNOOZED` |
| Row: checkbox · star · important · avatar · sender · subject+snippet · attach · date | `rowHtml()` |
| Hover actions replacing the date | `.gm-acts` / `.gm-row:hover .gm-when` |
| Select-all with predicates + partial-selection dash | `#gmAllCaret` · `[data-sel]` · `.gm-cb.some` |
| Bulk toolbar (archive · trash · snooze · read · unread) | `[data-bulk]` |
| Undo snackbar, no confirm dialogs | `snack()` · `moveTo()` |
| Density (comfortable · cozy · compact) | `body[data-density]` |
| Thread collapse + day grouping | `renderList()` |
| Replace-in-place conversation view | `.readpane` · `openMessage()` |
| Conversation action bar + ‹ › walk + keyboard | `renderReadBar()` · `readAction()` |
| Reply / reply-all / forward / print affordances | `#rReply` |
| Compose window | `sim/overlay/mail.js` (pre-existing) |
| Label chips, add/remove, tag picker | `renderTags()` · `tagPicker()` |
| Search with Gmail grammar passthrough | `#search` → mock `matchesQuery()` |

## F2 · Drive — built

| Component (Part B) | Where |
|---|---|
| System places incl. three standing queries | `SYS_PLACES` · `renderSysRail()` · `openPlace()` |
| Nested folder tree, drop targets throughout | `renderTree()` · `navLink()` |
| Breadcrumb path, every crumb a drop target | `crumbTrail()` · `renderCrumbs()` |
| Filter chips (type · modified · people) with per-chip clear | `renderChips()` · `applyFilters()` |
| List ⇄ grid toggle, persisted | `LAYOUT` · `renderList()` / `renderGrid()` |
| Grid cards with type-coloured thumbnail band | `renderGrid()` + `sim/overlay/drive.js` |
| Details pane, selection-aware, folder fallback | `renderDetails()` |
| Human type names | `typeName()` |
| Full-screen document view with ‹ › and keyboard | `preview()` |
| Share dialog (people → access → link) | `shareDialog()` |
| Storage meter with thresholds | `loadStorage()` · `renderStorage()` |
| Star as a mark, with undo | `toggleStar()` · `api/star` |
| Owner avatar + shared mark in the list | `renderList()` |
| Row hover actions · context menu · bulk bar · drag-move | pre-existing, extended to grid |
| Upload (drag anywhere, progress, XHR) | pre-existing |

## F3 · Deliberately NOT built, and why

- **Real thumbnails / image previews.** The grid band carries type colour + glyph instead. Real
  thumbnails need real bytes; the simulation has none, and faking them would make the map lie about
  what the platform can render today. The band is the component that survives the port either way.
- **Gmail's category tabs (Primary / Social / Promotions).** They exist to sort *consumer* mail. A
  business mailbox for one company has no social or promotional traffic — the tabs would be three
  permanently-empty compartments, which is worse than none. The sync labels do the real sorting here.
- **Drive's "Suggested" ML row.** Its value comes from a ranking model trained on the user's history.
  We have neither, and a "suggested" row driven by `created DESC` is a lie about how it works.
  דף הבית shows honest recency instead.
- **Multi-level undo / version history.** One-step undo covers the mistake people actually make.
  Version history is a backend capability, not a UI one — it belongs in the port, not the mock.
- **Offline / conflict states.** The simulation is offline by construction, so an offline banner
  would be permanently true and permanently meaningless.
- **Keyboard shortcut sheet (`?`).** The shortcuts that matter here (Esc, ⌘A, Delete, ‹ ›) are
  implemented; a shortcut *catalogue* is a documentation surface, and this file is that surface.

## F4 · Added after this study was written

Part F was drafted at the end of the rebuild; five things landed after it and belong in the ledger.

| Component | Where | Changelog |
|---|---|---|
| Dark theme for every new surface | `:root[data-theme="midnight"]` overrides in both apps | C14 |
| Touch targets ≥44px on coarse pointers | `@media (pointer:coarse)` in both apps + the compose overlay | C14.1 |
| Layered Escape (peel one overlay at a time) | `apps/mailview/app.js`, capture phase | C14.1 |
| Details pane dismissible when it is an overlay | `closeDetails()` + backdrop + Escape | C14.1 |
| Connection switcher in the console top bar | `overlay/switcher.js` | C15 |
| Grid fills its container instead of a fixed height | `BinaTable` `fill` prop | C16 |

**A rule this study should have stated outright, learned the hard way (C16):** a component must
never declare its own height. `BinaTable` defaulted to `height = 520`, which forced the page around
it past the viewport and produced two scrollbars on one axis. The billion-user products all do the
opposite — the shell owns the viewport, and each region takes the height it is *given*. Anything
else eventually fights the page it lives in.
