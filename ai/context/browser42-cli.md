# Browser42 Task CLI

Browser42 is one headed Chromium shared by agents and the human `/view`. It has one persistent
private profile, so cookies and logins are shared and survive container recreation.

Start the platform with `./bbox run` (on Windows use `bbox.cmd run`). Never start another browser
and never call Docker Compose directly.

## The Only Agent Loop

Use only `./bbox b42 task ...`. Do not use Playwright, CDP, Python, shell scripts, fetch/curl,
search engines, raw selectors, helper pages, or another task's tab.

### Fast path: `task goal` (PREFERRED — one command, no loop)

For "get the latest N items from this page" tasks, use the platform-side goal executor. It runs
goto → settle → best-container scan → extract → screenshot → verify → finish inside ONE command
with zero model turns (~30–90s even on ad-heavy sites):

```bash
./bbox b42 task goal <slug> <direct-https-url> [topic-keyword]
```

If the response has `"ok": true`, the task is ALREADY accepted and finished — the `records` in
that same response are the final result; report them and stop. Fall back to the inspect/act loop
below ONLY when `goal` returns `ok: false` (e.g. `goal_no_container`, `goal_insufficient_records`).

`goal` AUTO-STARTS the task when the slug does not exist yet, so `goal`-first and
`start`-then-`goal` both work. Never run `status` on a slug you have not started (it cannot
exist), and never repeat a command that just errored — fix the ordering instead.

### Fallback loop (only after a failed `goal`)

1. Choose one unique, immutable kebab-case slug and keep it unchanged for every command. Copy it
	verbatim from the first command into each later command.
2. Start the direct website requested by the user:

```bash
./bbox b42 task start <slug> <direct-https-url> [minimum-record-count]
```

Confirm the returned top-level `slug` exactly matches the one you supplied before continuing. If
another command's output appears in the terminal, ignore it and run `task status` with your own
immutable slug; never adopt a different task.

3. Retrieval goals ("get the latest N articles/items about a topic") — finish with ONE platform
   command. It runs goto -> settle -> pick best container -> extract -> screenshot -> verify ->
   finish with no further model turns, and returns the accepted records:

```bash
./bbox b42 task goal <slug> <direct-https-url> <topic>
```

   Pass the same direct URL you started (or a section URL) plus a short topic keyword. If it
   returns `ok: true`, the task is FINISHED: report the returned `records`, `final_url`, slug,
   and evidence, and stop. Only when it returns `ok: false` with `goal_no_container`,
   `goal_verify_rejected`, or `goal_insufficient_records` continue with the manual loop below.

4. Manual loop (interactive tasks, or the goal fallback) — repeat until the answer is visible:

```bash
./bbox b42 task inspect <slug> [visible-text-or-url-fragment]
./bbox b42 task click <slug> <handle>
./bbox b42 task fill <slug> <handle> <text>
./bbox b42 task press <slug> <handle> Enter
./bbox b42 task login <slug> <site>          # sign in with the office's own credential
./bbox b42 task read <slug> [max-chars]      # the WHOLE page as text, in one call (no scrolling)
./bbox b42 task screenshot <slug> <name> full  # the WHOLE document as one picture
./bbox b42 task captcha <slug> detect        # a human-verification challenge, if one is showing
./bbox b42 task captcha <slug> click <index> # answer it: 0, or 0,4,7 for a multi-select round
./bbox b42 task captcha <slug> click '@x:y'  # by PAGE pixel, when the DOM hides the widget
```

`read` is how an agent gets the **whole** page without scrolling it: this browser's viewport is small
(~780x395) and a transcript, a log or a long document does not fit in it. The verb walks the page's own
scroll container from top to bottom, reads the rendered text at each step, and stitches the steps by
their overlap (never by line equality, which would silently drop a legitimately repeated line),
returning `{text, chars, steps, stopped, scroll}` in one answer. Measured 2026-10-09: a 30,461-px
session transcript came back as 500,000 characters in 49 steps. Never scroll a page by hand to gather
context — read it.

`captcha` exists because a challenge lives in a **cross-origin iframe**, which `inspect` cannot see
(a page can show a Turnstile round while `inspect` reports no controls at all). `detect` returns the
kind, the instruction, every clickable target with its **page** coordinates and a picture of the
challenge; you — the caller that can see — pick an index; `click <index>` presses it like a hand.
After 3 clicks it refuses by name (`captcha_attempts_exhausted`) and hands the round to the owner at
`http://browser42.localhost:8080/view/` — never keep clicking, and never use a solver service.
Full background, measured results and the safety boundary: [captcha.md](captcha.md).

`inspect` returns at most 40 visible controls and 12 content containers with opaque `b42h:` handles.
ALWAYS pass a visible text or URL fragment — on ad-heavy sites an unfiltered inspect is slow and
its payload is large. Use only a handle returned by the latest inspection. Never invent a CSS
selector, page URL, or handle.

5. Record results and evidence:

```bash
./bbox b42 task extract <slug> <container-handle>
./bbox b42 task screenshot <slug> final
```

6. Complete only through acceptance:

```bash
./bbox b42 task verify <slug>
./bbox b42 task finish <slug>
```

`finish` is the only reportable result. It refuses tasks that are not accepted. Return the accepted
finish JSON, the direct final URL, the slug, and the task-owned evidence paths.

For a retrieval task, pass a plain numeric `minimum-record-count`; it automatically requires one
extraction and nonempty `text` and `url` fields. This avoids JSON/shell quoting. Advanced callers
may instead pass JSON with `minimum_extractions`, `minimum_records`, `required_record_fields`, and
`final_url_prefix`. Example:

```json
{"minimum_extractions":1,"minimum_records":5,"required_record_fields":["text","url"]}
```

Every command emits one JSON object with `protocol_version: 1`. Verification writes a durable
`result.json` matching `apps/browser42/task-result.schema.json`; it includes checks, extracted
records, native-group identity, screenshot hashes, and stage timings. Failures use
`error.code`, including `invalid_url`, `task_not_found`, `duplicate_slug`, `transient_cdp_failure`,
`operation_timeout`, `detached_target`, and `result_not_accepted`.

## Signing in: `task login <slug> <site>` (2026-09-27)

The office holds the accounts; the agent holds only their NAMES. The credential is not an argument,
and it appears in no journal entry, no response field and no log line — that is the point of the
command, not a side effect of it:

```bash
./bbox b42 task start fb-1 https://www.facebook.com '{"minimum_extractions":0,"minimum_records":0}'
./bbox b42 task login fb-1 facebook       # → {"ok":true,"site":"facebook","already_logged_in":false,…}
```

## One login, two stores: `bbox b42 logins` (2026-09-28)

Chrome's password manager and חיבורים ומפתחות are kept identical, in both directions, because "which
store is this password in" is not a question the owner should have to ask:

```bash
./bbox b42 logins list          # what Chrome holds (origins + username lengths; passwords never read)
./bbox b42 logins sources       # what the plane offers + the origin each credential maps to
./bbox b42 logins sync          # both directions (also runs automatically at every browser start, §4j)
./bbox b42 logins materialize   # plane → Chrome only   (native autofill in /view)
./bbox b42 logins harvest       # Chrome → plane only   (a credential appears in חיבורים ומפתחות)
```

The model, in four sentences: **the credential plane is the source of truth and Chrome is a mirror**
(the mirror is disposable and gives the human autofill); a login is `{origin, username, password}`
and the ORIGIN is the join key, taken from the credential's own `app.url` / `*_URL` field — there is
no per-site table, so a new site is a new credential and not a code change; **conflicts are decided by
which side moved since the last sync**, fingerprinted (HMAC, never the value) in
`data/browser42/browser-logins.json` — Chrome wins a genuine conflict because a human typed there;
**deletion is asymmetric on purpose** — removing a credential removes its Chrome row, removing a
Chrome row never deletes an office credential.

Chrome's manager never fills a field without a user gesture: a login can be present and the form
still look empty until the human clicks into it. That is normal, not a sync failure.

Two properties worth knowing before touching any of it: the container's Chromium uses its
**keyring-less "basic" store** (the key is derived, not stored — the script refuses a keyring-backed
profile rather than guessing), and the bridge is therefore only as private as the profile volume,
which is why that volume is backed up and `bbox b42 state dump` encrypts what leaves the machine.

What happens: the task runner leases ONE named connection from the credential plane
(`POST http://connections:8990/api/broker/lease`, identified by its own container id — see
`platform-base/connections/inject.sh` for the same identity trick), types the username and password
into the page over CDP, submits, and waits for the login form to be **gone**. The username and
password live only as local variables for the duration of that call.

- **Where the password is written, once:** חיבורים ומפתחות (`/a/connections/`) → the row
  `browser42-login-<site>` that this app declares in its own `app.json`
  (`contributes.connection_providers`). Nothing in `.env`, nothing to copy between environments.
- **Why it survives everything:** it is re-derived at every login, so a container recreate, an image
  rebuild or a profile wipe costs one command, not a re-login by the owner.
- **What is granted, to whom:** the connection names `service: browser42-task-runner` in the app's
  `connections[]`, which is the service the broker will hand it to and no other. That field is the
  reason this works at all: without it the broker would grant the secret to the app's routed service
  (caddy) and refuse the runner.
- **Sites:** `LOGIN_FLOWS` in `apps/browser42/group-manager.py` maps a site name to its login URL and
  selector lists (tried in order — a login page is markup we do not own). A site with no flow fails
  as `unknown_login_site`; a page where no selector resolves fails as `login_selector_missing` rather
  than typing a password into a guessed box; a missing credential fails as
  `credential_not_configured` with the screen to open.

## State And Safety

`start` creates one official colored/labeled native Chrome Tab Group and a durable record at
`data/browser42/tasks/<slug>/`. Task state is `allocated`, `active`, `accepted`, `rejected`, or
`stalled`. Every inspect/action refreshes the task lease. The platform watchdog marks a task
`stalled` only after five minutes without activity; it never closes the group, browser, profile, or
evidence. Use `./bbox b42 task status <slug>` to inspect state.

`goal <slug> <direct-url> [topic]` is the fast path documented above. Optional task commands are
`goto <slug> <direct-url>`, `wait <slug> [milliseconds]`, and `heartbeat <slug>`. `goto` accepts
only direct HTTP(S) URLs. `wait` is bounded to 15 seconds.

The CLI owns native grouping, shared-browser safety, ownership checks, evidence files, and
acceptance. Stop immediately on `rejected` or `stalled`; do not claim a result without `finish`.

## Cost, limits, and the editor fix (2026-09-22)

- **Limits in force since 2026-09-23 (browser42 2.0.0)**: `BROWSER42_CPUS=3` (the load run showed 2
  throttling the browser in 23.5% of periods and starving CDP, and 4 nearly doubling the office's
  latency), desktop 1280x800, container memory ceiling 1792M (the measured peak under three heavy
  pages in parallel was 1456MiB = 95% of the old 1536M).
- **Idle cost, measured**: 6 containers, ~0.7–0.9 GiB RAM and 6–12% of one core while nothing runs
  (every other container in the estate is under 1.5%). It is the office's largest idle consumer, so
  stop it when it is not in use — see the `office-browser` skill for the enable/stop commands, the
  `BROWSER42_CPUS` cap and the desktop size, and `scripts/ops/quiet-mode.sh` for the platform's own
  under-pressure posture.
- **The composer gap**: `inspect` derives an element's name from `aria-label`, `placeholder`,
  `innerText`, `value` — a modern contenteditable editor (Facebook's post box, any Lexical/Draft
  box) has role=textbox with an EMPTY accessible name and only `aria-placeholder` to describe
  itself, so it used to be collected and then discarded. Fixed in `apps/browser42/group-manager.py`
  by adding `aria-placeholder`/`data-placeholder` to the name sources and a matching fallback in
  `locate()`. Verified by publishing a post end to end (`ai/context/setup-facebook-login.md`).
- **Editing a bind-mounted app file on macOS/Lima**: the container can keep serving a truncated
  older copy over virtiofs (`SyntaxError` from a file that parses on the host). Restart the
  container that reads it — `./scripts/dc restart browser42-task-runner` — and confirm with
  `docker exec <ctr> md5sum /group-manager.py` against the host.

## The live view's clipboard (one clipboard, not two) — 2026-09-22

The owner's `/view/` page used to move text only through noVNC's manual Clipboard panel: noVNC 1.6
ships nothing else (verified in `app/ui.js` — only `clipboardReceive`/`clipboardSend`), and every
keystroke is `stopEvent()`ed by `core/input/keyboard.js`, so the browser never performs its own
paste either. There is no way to "just remove the interception": the view is a bitmap, so there is
no local field to paste into.

`apps/browser42/browser-clipboard.js` (injected exactly like the navigation toggle, section 4b of
`start-browser.sh`) implements the design KasmVNC ships as **clipart seamless / clipboard up +
down / translate keyboard shortcuts** — the productized noVNC fork, and the accepted way this is
done in a browser VNC client. Upstream noVNC has it as an open request (novnc/noVNC#1511).

- `Cmd+V` / `Ctrl+V` → the local clipboard is read once and pushed as **one** RFB cut-text, then a
  real Ctrl+V is sent to the remote. `Cmd+C` is translated to `Ctrl+C` because the remote desktop is
  Linux (KasmVNC's documented behaviour for macOS clients).
- Remote → local needs **no** permission at all (`writeText` on a focused document); a constant
  `SYNC_REMOTE_TO_LOCAL` in the module turns that direction off.
- Local → remote needs Chromium's **one-time** grant, per origin — the only door a page has to the
  OS clipboard. Declining is harmless: the push is skipped, Ctrl+V still forwards, the panel stays.
  Chromium-only; Safari/Firefox keep the panel (as in KasmVNC).
- `Cmd+X` / `Ctrl+X` counts as a copy for that gate — the 2026-09-23 report was "Ctrl+X deletes but
  does not update the clipboard", because only `C` set the copy intent while the cut's clipboard
  change was therefore skipped as if it were a selection.
- The paste path always synthesizes its own **Ctrl**, never assuming noVNC forwarded a physical
  Ctrl-down. Skipping it when the event carried a `ctrlKey` looked like a harmless optimization and
  made the paste type a literal "v" — caught by the up-direction test the same day.
- Requires a **secure context**: `browser42.localhost` and the console embed qualify, a bare
  container hostname does not — that is why the tests below connect through `*.localhost`.

Verified inside the container's own Chromium (both directions, no owner needed):
`window.__b42clipboard` exposes `attached`, `pushes`, `remoteWrites`. A `Ctrl+V` keydown on the
viewer put `B42-CLIP-TEST-42` into a textarea of another tab, and a trusted `Ctrl+C` inside a tab
put `B42-COPY-FROM-CLOUD-7` into the local clipboard. Note for future tests: a *dispatched*
`KeyboardEvent` cannot drive a browser's built-in copy/paste; use CDP (`page.keyboard.press`).

Also fixed in the same change: the section-4b injection was not idempotent, so **every container
restart added another copy** of the navigation button and script (two of each were found in the
running viewer; a duplicated clipboard module would push each paste twice). It now strips its own
previous injections before inserting one of each.

## The profile can no longer be lost — root fix (2026-09-23, completed 2026-09-27)

**What actually happens.** cloakserve deletes the whole profile (`/profile/__default__`, every cookie
and login) when its Chrome child does not answer CDP in time; it guards its *shutdown* rmtree, not
the startup one. Two measured incidents: 2026-09-22 (cold start, Facebook login gone, no backup) and
**2026-09-23 10:29 — with the container's `StartedAt` unchanged since 09-22 17:03**, i.e. cloakserve
tore down and relaunched its Chrome *mid-life* and wiped the profile on the way. A boot-time-only
guard would have missed that one, which is why the fix watches for the life of the container.

> **⚠️ 2026-09-27 — the sentence this section used to open with ("a third-party, digest-pinned binary,
> so the deletion cannot be patched out") was simply wrong, and it cost the owner his Facebook login
> again.** cloakserve is plain Python, and `Dockerfile.browser` patches it twice already. The startup
> rmtree is now guarded there too: for the reserved seed the profile is **quarantined**
> (`<dir>.corrupt-<epoch>`), not deleted. The guard below stays as the second line of defence, because
> a profile can still be lost by a path nobody patched.

**What stands in the way now** (all in `apps/browser42/start-browser.sh`, sections **4h** — the profile
guard — and **4i**, its runtime watcher, plus the Dockerfile patch):

| Layer | What it does |
|---|---|
| No destructive recovery | `Dockerfile.browser` guards cloakserve's **startup** rmtree for `RESERVED_SEEDS`: the profile is renamed aside, never deleted. This is the one that removes the cause. |
| Snapshot outside the volume | `/profile` is copied to `data/browser42/profile-snapshot/` on the *host* — it survives a container recreate and an image rebuild. Refreshed 2 min after boot and every 5 min after. |
| Wipe-proof promotion | A snapshot is only replaced by a live profile that still looks real (`Local State` + `Cookies` + ≥3 cookie rows) **and that holds MORE cookies than the snapshot already does**. A wiped profile (0–1 cookies) and a merely LOGGED-OUT one can therefore never overwrite the last good copy. |
| Kept generation | The copy a promotion replaces is kept as `profile-snapshot.prev` rather than deleted, and the restore falls back to it when the primary snapshot is unreadable. Nothing here may be the step that loses the only good state. |
| Restore at boot | Every start checks the profile first and restores the snapshot when it looks wiped. |
| Runtime watcher (20s) | Detects a mid-life wipe, restores, then drops the Chrome child so Docker restarts the stack on a profile that is whole again. |
| No premature kill | The CDP watchdog now waits for the **first successful probe** (15 min backstop) instead of a fixed 45s grace — the old grace was shorter than a cold start, so it killed a browser that was still coming up, and that restart is what turned a slow start into the 09-22 wipe. |

**The 2026-09-27 failure, and why the guard above did not catch it.** The guard reasoned about
"wiped" (0–1 cookies) and had no notion of "logged out". A profile that is signed out of everything
still carries ~25 tracking cookies (facebook: `datr`/`fr`/`sb`/`wd`), so it passed `profile_is_real`,
**overwrote the snapshot within five minutes of it being taken**, and every later restore restored a
logged-OUT profile. The measured evidence: the snapshot's own cookie store contained no `c_user`/`xs`
— i.e. the "backup" had never held a login. Fix: promotion is now monotone in cookie count (logging
in only ever adds cookies, logging out removes them), so a state with nothing to add cannot replace
one that holds a session.

**Acceptance: proven by deleting the live profile, twice.** After the 2.0.0 rebuild the profile was
wiped on purpose (`rm -rf /profile/__default__`, exactly what cloakserve does) and the system
repaired itself — the container's own log is the record:

```
[profile-guard] snapshot updated (97M, cookies=32)
[profile-guard] profile is missing or wiped — restoring from the snapshot     <- the boot path
[profile-guard] restored: cookies=32 at 98M
[profile-guard] WIPE DETECTED at runtime — restoring the snapshot and restarting Chrome
[profile-guard] profile is missing or wiped — restoring from the snapshot     <- the runtime path
[profile-guard] restored: cookies=32 at 98M
```

A wipe is detected in ≤40s (two reads, 20s apart), restored, Chrome restarted, and the container
comes back with all 32 cookies and its session. Unit tests of the guard functions cover the logic
(real profile detected → snapshot → wipe detected → restore returns the cookies → a wiped profile can
never overwrite a good snapshot → **a logged-out profile can never overwrite a signed-in one** → a
fresh deployment with no snapshot is never touched → the `.prev` fallback restores when the primary
snapshot is unreadable).

**Two bugs this acceptance test caught, both of which would have shipped silently:**

1. **A WAL false negative.** `profile_cookie_count` copied only `Default/Cookies`; Chromium keeps
   that store in WAL mode, so a copy taken while Chrome was writing presented **zero** rows and a
   perfectly healthy profile looked wiped. The counter now copies `-wal` and `-shm` too and retries
   three times. Symptom it caused: the runtime guard stayed asleep through the first acceptance run.
2. **A transition gate that could never fire.** The runtime guard originally required having observed
   a healthy profile *first* (`last_state = real`) before it would restore. One false negative at the
   wrong moment and it would sleep forever — which is precisely what happened. It now fires on **two
   consecutive wipe readings**, with no dependency on history.

## One browser, always (2026-09-23)

- **The window is FITTED, by geometry, every 2s** (section 2b) — not "maximized once". Two silent
  bugs were behind the owner's 2026-09-23 report ("not full screen, and the top is cut off"):
  1. the loop filtered windows with `xdotool search --class Chromium-browser`, but this build's
     WM_CLASS is `chromium (/profile/__default__)`, `Chromium` — **it matched nothing**, so the loop
     had been a no-op and the window sat at a stale `y=-50, 1050x760` on a 1408x793 desktop (title
     bar and tab strip above the visible area). Window discovery now matches the class column of
     `wmctrl -lx`, which cannot rot with a rename.
  2. `wmctrl -e` wants **five** comma-separated integers (gravity,X,Y,width,height); four fails with
     `exit 1` and, under the loop's `|| true`, looked applied and was not. The fit uses
     `xdotool windowmove`/`windowsize` instead — verified by deliberately misplacing the window and
     watching it snap back within one cycle.
  Fullscreen (F11/compact) windows are skipped, so the toolbar toggle still wins; and because the fit
  re-reads the screen size every cycle, a `resize=remote` desktop change is tracked automatically —
  which is the case a one-off maximize could never handle.
- **Window convergence** (section 2c): at boot, keep the first Chromium window and close the rest.
  Extra windows appear because every failed launch in the CDP retry loop leaves its own behind (three
  were found in the owner's taskbar) and because a link opened "in a new window" adds another. Safe
  at boot — all windows share one profile, so nothing is lost, and nothing is in progress. Closing is
  deliberately boot-only: a background janitor would also close a window the owner opened on purpose.
- **The wallpaper dialog**: `fbsetbg` (fluxbox's wallpaper helper) finds no setter in this image and
  pops a modal `xmessage` that nobody dismisses — one per fluxbox start, 44 had accumulated. Two
  layers: `session.screen0.rootCommand: true` in `~/.fluxbox/init` stops the call at the source (the
  style's rootCommand cannot run), and a 5-second sweeper reaps any dialog a future style change
  brings back.

## 2.0.0 — what shipped (2026-09-23)

Clipboard bridge with the owner's computer (KasmVNC-style: Cmd/Ctrl+V up, Cmd+C/Cmd+X translated to
Ctrl+C/Ctrl+X down, copy-intent gate, `SendPrimary=0`); resource caps and the measured load report;
`inspect` able to address contenteditable editors; the profile guard above; one-window convergence;
the fbsetbg dialog fix; and the failure modes each of those came from, documented in this file.
