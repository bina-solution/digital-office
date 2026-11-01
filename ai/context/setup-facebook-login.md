# Facebook / Messenger — driving via browser42

Drive over CDP per [`browser42-cli.md`](./browser42-cli.md) (the `bbox b42 task` loop, or
`scripts/fb-send.py` for a DM): `connect_over_cdp("http://localhost:9222")` from inside the
browser42-browser container.

## Session status — CHECK IT, never assume it

**The profile is NOT permanently logged in.** It was logged in as the Bolotin family account
("Shlomo Bolotin"); on **2026-09-22** it was logged out and the profile was wiped — see the
incident below. As of that same day the owner signed back in through the live view and a post was
published from it (`fb-post-1755`), but **no `state dump` exists yet**, so the next profile wipe
costs a full re-login again. Verify the session before any Facebook task:

```bash
./bbox b42 task start fb-state https://www.facebook.com '{"minimum_extractions":0,"minimum_records":0}'
./bbox b42 task inspect fb-state "Log in"        # controls present ⇒ logged out
./bbox b42 task screenshot fb-state fb-state
./bbox b42 task verify fb-state && ./bbox b42 task finish fb-state && ./bbox b42 close fb-state
```

Logged out ⇒ the owner signs in once through the live view (`http://browser42.localhost:8080/view/`,
the tab is shared, so the session then serves every agent), and **immediately afterwards run
`./bbox b42 state dump`** so the session survives a container recreate. That dump needs
`BROWSER42_STATE_PASSPHRASE` set in `.env` (empty today) — and it stops the browser container for a
consistent snapshot, so run it when nothing else is in flight.

## Incident 2026-09-22 — a cold start WIPED the profile (unrecoverable)

The container had been idle for ~4 days. On the first start Chrome cold-started slowly, CDP
answered `502` for ~60s, cloakserve retried by launching a fresh Chromium six times, the compose
healthcheck marked the container unhealthy, autoheal restarted it — and the profile directory
`/profile/__default__` came back **empty** (`Birth: 2026-09-22 13:27`, 1 cookie: a `google.com`
`NID` Chrome sets for itself). All Facebook cookies were gone, and there was no `state dump`
to restore from. `start-browser.sh` documents this exact failure mode: cloakserve's CDP-timeout
handler `rmtree`s the profile to recover, and it guards only its *shutdown* rmtree, not the
startup one.

Consequences: (1) a `state dump` after every sign-in is not optional; (2) do not
`docker restart`/`stop`/`up` the browser container while a session matters; (3) a warm restart
is fine (~18s to healthy, one Chrome launch) — it is the *cold* start that is dangerous.

## Sending a message to a person (verified)

1. Resolve the profile: `https://www.facebook.com/search/people/?q=<Name>`, read anchor
   hrefs whose text matches — e.g. `William` → friend profile **`willi.bolotin`**
   ("Willi" = short for William; confirm with the **Friends** button + mutual-friends count,
   the look-alikes named "William <other surname>" are non-friends).
2. Open the profile (`https://www.facebook.com/willi.bolotin`) and click the blue
   **Message** button (`get_by_role("button", name="Message").first`).
3. Type into the popup textbox `aria-label="Write to <Name>"`, then `press("Enter")`.
   Confirm: textbox goes empty and a bubble with the text appears.

## Posting to the owner's timeline (VERIFIED 2026-09-22)

Ran end to end on the owner's account from `fb-post-1755`: the post appeared in the feed, with the
`digital-office.co.il` link rendered as a preview card. Evidence:
`data/browser42/tasks/fb-post-1755/screenshots/{before-post,after-post}.png`.

```bash
./bbox b42 task start fb-post-<stamp> https://www.facebook.com/ '{"minimum_extractions":0,"minimum_records":0}'
./bbox b42 task inspect fb-post-<stamp> "mind"    # the composer trigger: button "What's on your mind, <name>?"
./bbox b42 task click   fb-post-<stamp> <trigger-handle>   # opens the create-post dialog
./bbox b42 task inspect fb-post-<stamp> "mind"    # NOW the editor: role=textbox, same placeholder text
./bbox b42 task fill    fb-post-<stamp> <textbox-handle> "<post text>"
./bbox b42 task screenshot fb-post-<stamp> before-post
./bbox b42 task inspect fb-post-<stamp> "Post"    # button named exactly "Post" (or "פרסום")
./bbox b42 task click   fb-post-<stamp> <post-button-handle>   # PUBLISHES
./bbox b42 task screenshot fb-post-<stamp> after-post
./bbox b42 task verify fb-post-<stamp> && ./bbox b42 task finish fb-post-<stamp> && ./bbox b42 close fb-post-<stamp>
```

Rules and traps, all hit for real:

- The editor and the Post button only exist **after** the dialog opens — inspect twice, and never
  reuse a handle from before the click. A "Comment as …" box on someone else's post is never the
  composer.
- The editor is a `div[contenteditable][role=textbox]` with **no `aria-label`**; its only hint is
  `aria-placeholder="What's on your mind, <name>?"`. Until 2026-09-22 `inspect` collected it and then
  dropped it for having an empty name, so the composer was unreachable — fixed in
  `apps/browser42/group-manager.py` (name falls back to `aria-placeholder`/`data-placeholder`, and
  `locate` falls back to `[role=…][aria-placeholder=…]` when the accessible name is empty).
- Do the whole flow in ONE continuous run: the task watchdog marks a task `stalled` after 300s
  without activity, and a stalled task fails its ownership check (`expected one live tab, found 0`).
- `fill` never presses Enter; the Post click is the publish action — the one irreversible step.
  Show the owner `before-post` (the dialog with the text and the link card) before clicking.
- A URL in the text becomes a preview card automatically; confirm the card resolved before posting.

## Editing a post that is already published (VERIFIED 2026-09-22)

Facebook keeps the original post and its timestamp — an edit is not a repost, so nobody is
re-notified. Ran as `fb-edit-1807` (text changed from "לעסק שלך" to "לעסק שלכם"); evidence:
`data/browser42/tasks/fb-edit-1807/screenshots/{before-save,after-save}.png`.

```bash
./bbox b42 task start fb-edit-<stamp> https://www.facebook.com/<vanity> '{"minimum_extractions":0,"minimum_records":0}'
./bbox b42 task inspect fb-edit-<stamp> "Actions for this post by <owner name>"   # the post's ⋯ menu
./bbox b42 task click   fb-edit-<stamp> <actions-handle>
./bbox b42 task inspect fb-edit-<stamp> "Edit post"        # menuitem inside the opened menu
./bbox b42 task click   fb-edit-<stamp> <menuitem-handle>  # opens "Edit post" with the current text
./bbox b42 task inspect fb-edit-<stamp> "mind"             # the editor — same aria-placeholder trick
./bbox b42 task fill    fb-edit-<stamp> <textbox-handle> "<new text>"
./bbox b42 task screenshot fb-edit-<stamp> before-save
./bbox b42 task inspect fb-edit-<stamp> "Save" && ./bbox b42 task click fb-edit-<stamp> <save-handle>
./bbox b42 task screenshot fb-edit-<stamp> after-save
./bbox b42 task verify fb-edit-<stamp> && ./bbox b42 task finish fb-edit-<stamp> && ./bbox b42 close fb-edit-<stamp>
```

Traps specific to the edit:

- The post's ⋯ menu is reachable on the owner's **timeline** (`facebook.com/<vanity>`), where its
  aria-label is `Actions for this post by <owner name>`. On the home feed the post can be below the
  fold, and `inspect` only sees visible elements, so it will not be found there.
- `fill` **replaces the whole editor content** — no need to select-all first.
- The link preview card survives the edit (verified) — but check `before-save`: the card is an
  attachment of the post, and `fill` rewrites the text around it.
- `Save` (not `Post`) commits the edit; that is the publish-equivalent step for an edit.

## Gotcha — Messenger E2EE "Enter your PIN to restore your chats"

Opening Messenger (`/messages/t/`) pops a hard **PIN restore** modal. Closing it via its ✕
re-triggers a **"Continue without restoring?"** confirm — it loops; the only exits are the
PIN or **"Don't restore messages"**. Per autopilot policy, click **"Don't restore messages"**
(reversible later via PIN; just skips loading old E2EE history) and continue — sending NEW
messages works fine afterward. Messaging straight from the **profile page** still shows the
same gate, so dismiss it once. See the popup-autopilot memory.

## Notes

- Messenger's left search only finds existing chats/contacts — pressing Enter there navigates
  to the full `facebook.com/search/top/?q=` results page (use that for new people).
- Clicking **Message** from the search-results card sometimes drifts the tab to the home feed;
  going via the profile page is the reliable path.
- "Remember password" / "Save info" nags: dismiss with **Not now** / ✕.
