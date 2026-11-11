# bina-claude — «בינה קלוד»

**Bina Claude is ONLY the official Claude Desktop app with ONE login; there is no terminal; never propose
/login or a terminal.** The owner, 2026-11-09 (DGO-1684): «one login in the official claude desktop and we
should have full cli controll over it and all other 4 channels» … «Delete the terminal and make sure nobody
gets mixed up again». Gate G105 (`scripts/refactor/one-claude-lint.py`) fails a tile, a host or a doc that
brings a terminal back.

The owner, 2026-10-31 (DGO-1074): «focus on having just the Claude inside and fully controllable via CLI,
API, and UI … so it can be used from Azaria, from Bina DS».

## What it is

Two containers on one volume (`bina_claude_home`), four channels on ONE sign-in:

| Channel | What | Where |
|---|---|---|
| UI | **the official Claude Desktop app for Linux** (apt `claude-desktop`), streamed by Selkies | the console tile «בינה קלוד», `/a/bina-claude/` (service `bina-claude-desktop`) |
| CLI | `./bbox agent --app bina-claude list\|new\|send\|follow\|log\|cancel …`, `./bbox bina-claude status\|signed-in\|ask\|sessions\|show` | any shell of the office, any agent; another office's with `--office` |
| API | agent.v1 ([agent-contract.md](../../ai/context/agent-contract.md)) over **the desktop app's own sessions** (DGO-1298) | `http://bina-claude:3091` in the office network; `127.0.0.1:3091` on the docker host (service `bina-claude`, the adapter alone) |
| Flow | the office timeline's lane `bina_claude` (`adapter/spans.mjs`, `SPAN_SOURCE_BINA_CLAUDE`) | «כל מקביל» (any-concurrency) |

## The desktop app, natively (Selkies)

The owner, 2026-10-31: «I want everything to be natively like I installed the software … native Docker
for Linux containered and served like I serve browser 42 … I'm not sure if VNC is the best way».

The app is installed exactly as Anthropic's Linux docs say (their apt repository, key fingerprint
checked in the build) on linuxserver.io's `baseimage-selkies` (Debian trixie, X11 mode), and runs as the
image's user `abc` with HOME `/config` = the volume's `desktop` folder, so its Claude Code sessions are
office data (`./bbox bina-claude sessions`). Its sign-in is kept in a GNOME keyring unlocked at every
start (`desktop/autostart`), so it survives restarts and recreates (measured on Exampleu, 2026-11-09).

Why Selkies over VNC (research on DGO-1074): H.264 decoded by the browser (WebCodecs) over ONE websocket —
no UDP or TURN, so it passes Traefik + SSO like every app — resize to the browser window, a pinned DPI
(`BINA_CLAUDE_DESKTOP_DPI`, 96–288), clipboard both ways with images, file upload/download, phone touch
and IME input. noVNC (browser42's stack) sends soft JPEG text and a text-only clipboard. Not available
in a container: Cowork (it needs `/dev/kvm`).

**The stream needs a secure context.** The browser decodes it with WebCodecs, which a page served over
plain HTTP from a non-localhost name refuses ("FATAL: Not in a secure context. WebCodecs require
HTTPS", measured 2026-10-31). `console.localhost` (the Mac) and an HTTPS office (vps1) are secure; an
office opened at a LAN IP over HTTP is not, and shows the sidebar without the picture.

The front door is `adapter/gate.mjs`, an s6 service here: the image's nginx is moved to the container's
loopback (:3100) at build, and :3000 admits only the edge, the console and the link proxy, by address.

Measured on the Mac (2026-10-31): claude-desktop 4.4212.0, Selkies 2.1.0 (websockets, x264 on the CPU),
the container at ~400 MB, the app at ~11 % of a core when idle.

### The office, in every desktop session (DGO-1275)

The owner: «It should by default have the digital office directory the hp has like azaria gets in
bina-ds». The app's Code sessions get the office with nothing chosen by hand:

- the checkout is mounted in the desktop container at its host path, and `/workspace/office` points at it
  (the launcher keeps the link; `/workspace` is the desktop user's in the image); the app is started there;
- its `~/.claude/CLAUDE.md` is the office brief, written by `entrypoint.sh` into the desktop's home
  (`/data/desktop`): it is inside the DGO, the office is `/workspace/office`, read `AGENTS.md`, and
  `./bbox` and `./scripts/dc` run in the app itself — it has the office's docker (DGO-1323);
- its `~/.claude/settings.json` has `/workspace/office` in `permissions.additionalDirectories` and
  `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1`, MERGED into whatever the app and its owner keep there:
  every session reaches the office and loads its own CLAUDE.md/AGENTS.md, whatever folder it opened in.

**The app works in the office as the checkout's owner** (DGO-1684): `BINA_CLAUDE_DESKTOP_PUID` /
`BINA_CLAUDE_DESKTOP_PGID` in the office's `.env` are the owner of its checkout (`stat -c %u:%g <checkout>`) —
1000 where a person's home holds it (the default), `0` on a server office whose checkout is root's under
`/root` (Exampleu). As 1000 there, the app could not even list the checkout, so no session could work in it and
the folder picker could not offer it. Root adds no power the app does not have: it already holds the engine's
socket. Changing the value re-owns what in the app's home is not that user's, at the next `up`
(`bina-claude-desktop-home`); back the home up first. (A uid other than 0 or 1000 also needs `/workspace` to
be that user's: the image gives it to 1000.)

**The office is the default folder of a new session.** Claude Desktop documents no default folder
(code.claude.com/docs/en/desktop): a new session opens in the folder the New page has selected, and the app
asks «Trust this workspace?» the first time a folder is chosen — and for every folder a `claude://` link hands
it, trusted or not, so the driver never sends one. Once `/workspace/office` was chosen and trusted on the New
page (Exampleu, 2026-11-09, «Saved workspace trust for /workspace/office»), every new session — from the screen
or from `bbox agent … new` — opens in the office, and the picker shows it as «office». A session elsewhere
still sees the office through the brief and the additional directory.

## Opened from another office (the HP's Claude on vps1)

The owner, 2026-11-01: «run on the HP … give me the link from the VPS … because HP shares its apps with
the VPS DGO, I will be able to use that Claude account from everywhere». An office shares the desktop
tile like any app — its `serve:` names `bina-claude` for the consuming office — and three things in this
app make the shared tile work:

- Selkies is served at the root (`SUBFOLDER=/`): its client derives every route from the page's own path,
  so the same server answers the local console's `/a/bina-claude/` (prefix stripped) and the shared host
  `bina-claude.<office>.console.<domain>` (root).
- The front door admits the link proxy (`dgo-net`) besides the edge and the console: the consuming
  office's own edge has already signed the person in.
- The consuming console must be allowed to frame it: `BINA_CLAUDE_FRAME_ANCESTORS` in the SERVING office's
  `.env`, comma-separated and the whole value in double quotes (unquoted, the leading `'self'` loses its
  quotes and becomes a host name) — on the HP,
  `BINA_CLAUDE_FRAME_ANCESTORS="'self',http://console.localhost:8080,https://console.staging.digital-office.co.il"`.

The stream needs a secure context, and vps1's HTTPS console is one.

## Signing in — once, in the desktop app

«Continue with Google» opens Google's own sign-in page in a browser on the SAME screen the tile streams,
on a computer or a phone (`desktop/signin-browser`: Chromium, maximized, in a throwaway profile deleted
when its window closes — no Google session stays in the office). After the account choice, claude.ai
answers with a `claude://` link; the browser's policy lets claude.ai open it without a prompt, and the
app's own handler takes it to the running app (`desktop/claude-desktop`, first on PATH: the package's
handler starts the app without `--no-sandbox`, which dies in a container). The answer closes the sign-in
window. Both ends are logged, by host and path only, in `/config/.claude-open-url.log`; `signin-log.awk`
reads what became of the last press. The browser is for the sign-in ONLY: it runs without Chromium's
sandbox as a user that can reach the host's docker socket, so it opens nothing but the app's sign-in on
claude.ai/claude.com (any other link the app opens is not opened, and is logged by its host), lives 15
minutes at most, and downloads nothing.

Or «Continue with email»: open the e-mail's link on the PHONE, in its browser (not in the Claude app,
which can take the link over), and type the code it shows into the app
(support.claude.com/en/articles/13189465).

The sign-in is kept in the desktop's GNOME keyring on the same volume, unlocked at every start
(`desktop/autostart`; without an unlocked keyring the app keeps no token and signs out at every launch —
DGO-1335). Measured on Exampleu (2026-11-09): the app's cookie key («Claude Safe Storage», made at its first
start) and a probe secret stored the same way were unchanged after a restart, a recreate and a new image.

`./bbox bina-claude signed-in` says whether it is signed in and why not, from its cookie and its own log
(when it last started, whether it was signed in then, a renewal claude.ai refused, the last sign-in
attempt and how it ended). The cookie leaving the disk while the app runs is NOT a sign-out: the app's own
start record decides (DGO-1684). Exit 0 = signed in, 3 = signed out, 1 = not running or unknown. A lost
sign-in rings a notice by itself (`adapter/signin-watch.mjs`, the office's notifications app).

**Why the desktop never started on a fresh office** (Exampleu, 2026-11-08): its home is a SUBPATH of the
volume, and Docker refuses to start a container whose subpath does not exist yet — it stays Created for
good, since a restart policy acts only on a container that ran. The adapter's entrypoint made the folder,
but `depends_on: service_started` waits for the container, not its entrypoint. The one-shot
`bina-claude-desktop-home` now makes it first (DGO-1506).

## When it is signed out, the office says so (DGO-1430)

A Claude that has lost its account is not idle, it is stuck. On 2026-11-04 07:29 UTC the desktop app lost
its claude.ai session and stayed signed out for 48 hours: the manager and the group bot that run in it
stood still, and nothing in the office said a word. The alarm is the adapter's, and it is generic — it
asks the same `login()` that `bbox bina-claude status` asks (DGO-1347: whether the claude.ai session
cookie is in the app's own store, never a value).

- Every 60 s the adapter reads `login()`. `logged_in === false` **without a break** for
  `BINA_CLAUDE_SIGNOUT_GRACE_S` (default 180 — the app's start-up flap is 1–4 s and a sign-in in progress
  about a minute; a value that is not a positive number of seconds is refused, logged, and 180 is used)
  is ONE episode, and it posts one notice to «התראות»: source `bina-claude`, source_id
  `signed-out-<epoch the episode began>`, level `error`, titled «Claude נותק מהחשבון — הסשנים בו עצרו»,
  with a body that says when in the owner's clock — «מאז HH:MM», or «נמצא מנותק ב-HH:MM» when the alarm did
  not see the beginning — **with the date when it was not today** («04.11 09:29»; a three-day-old sign-out
  must not read as this morning), and gives the address to sign in at. The relay writes the title and the
  body and **not** the notice's `link` field — so the address is in the body.
  The episode records whether its beginning was **watched** — a «signed in» reading no more than two ticks
  (120 s) before the first «signed out» one, in this process or in the state it loaded (`last_in`). An
  adapter that starts on an app that is *already* signed out — or that comes back after hours of unreadable
  readings — watched no beginning, and says so instead of claiming one (the second reader, 2026-11-06: the
  first line said «מאז 13:28» — the adapter's own start — while the app had been out since 2026-11-04
  07:29 UTC; a «signed in» flag that was never cleared made the same claim after any long gap).
- `logged_in === true` closes an announced episode: the SAME source and source_id at level `info`
  («Claude מחובר שוב», «ההתראה מ-HH:MM נסגרה»), and the episode ends with that line — the notice is then
  marked read **best effort** (a read that fails is logged and the episode is closed anyway). The board is
  asked before the close is written: an episode whose red line never landed is forgotten rather than closed
  with a green line about nothing, and one whose closing answer was lost already reads `info` there — so
  there is never a second green line. An episode that ended inside the grace says nothing.
- Both lines reach the owner's group through a rule of their own, `bina-claude-signout` in
  `apps/dashboard/group-events.json` — before `errors`, **uncapped**, with no repeat window (both carry the
  same source_id, so a window would swallow the close). The relay reads that list once at its start: a
  rule change needs the `dashboard-group` container restarted, not just saved.
- `logged_in === null` — the store is not readable, the app's container is away — is **not** a sign-out
  and changes nothing.
- The episode (`{began, seen, posted, notice, attempted, last_in}`) is kept in
  `${BINA_CLAUDE_STATE}/signout.json` on the app's volume, so a restart of the adapter neither posts twice
  nor forgets an open one. Two rules make that hold when the board is slow — it is one gunicorn worker on
  sqlite, and an answer can arrive after the 10 s abort:
  - `attempted` is the source_id of a POST that **may** have reached the board, and it is written to the
    volume *before* the POST leaves. A source_id that may exist is never posted blind: the retry asks the
    board first (one GET), and a board that cannot answer means the tick is skipped, not a second red line.
    A board that answers «not there» lets it post; one that answers «already there» adopts it.
  - an episode whose write was attempted is never forgotten on the sign-in: the board is asked, and a red
    line that landed late is closed — the group's last word is not left red for ever.
  A state file that is there but is not JSON is logged, and the episode it still names is salvaged from the
  text — `began` above all, since the close's source_id comes from it: a number is read only where it ends
  (a half-written `17939645` is not a 1970 beginning), and nothing before 2026 is believed.

The decision is one pure function, `decideSignout(state, observation, now)` → `(state, action)`, and the
turn that carries it out (`alarmStep`) is handed the board's three calls **and the pen** (so the write that
may have left is on disk before it leaves) — both are tested without a clock, a container or a network:

```bash
node --test apps/bina-claude/adapter/test_signout.mjs
curl -s http://bina-claude:3091/v1/health | jq .signout     # the alarm's own state, live
```

`adapter/server.mjs` is mounted over the image's copy (`docker-compose.yml`) — so this lands with a recreate of
`bina-claude` and **no image build**. Settings (`.env`): `BINA_CLAUDE_SIGNIN_LINK` (the address the person
needs — for the HP `https://console.staging.digital-office.co.il/#/m/bina-claude.hp-laptop`, the console's
own route for the tile: `/a/<alias>.<office>/` exists only for a tile carrying a `door`, and this one is
`external`, so it answers «unknown_app» after the sign-in — DGO-1433; empty = the words «האריח «בינה קלוד»
בקונסול»), `BINA_CLAUDE_SIGNOUT_GRACE_S`, `BINA_CLAUDE_NOTIFY_URL`, `BINA_CLAUDE_TZ` (the clock the hour is
said in; empty = Asia/Jerusalem, never the container's `TZ`).

## The API

The owner, 2026-11-03 (DGO-1295): ONE Claude — the official app — and «כל מה שאני יכול לעשות מתצוגה
אני … יכול לעשות מהשורת פקודה». So agent.v1 serves **the desktop app's own sessions** (DGO-1298): the id
is the app's (`local_…`, the id of its sidebar), a session started from the CLI is on its screen, and the
turns run in the app, on the owner's account. The adapter runs no Claude of its own.

- **Read** — the app's files on the shared volume (`/data/desktop` is the app's HOME): its record of each
  session (`.config/Claude/claude-code-sessions/*/*/local_*.json`), the Claude Code transcript
  (`.claude/projects/*/<cliSessionId>.jsonl`, translated into the contract's events, so `bbox agent
  follow|log` renders Claude's tool calls and text exactly as it renders Azaria's), and live
  busy/waiting/idle (`.claude/sessions/<pid>.json`; a file older than the running app's `SingletonLock`
  was left by a process that died with an earlier run of the app, and is not live).
- **Write** — [`desktop/drive`](desktop/drive), run inside `bina-claude-desktop` with `docker exec` (its
  source is handed to python, so it works wherever the office keeps its checkout): the app has no local
  API, so it uses the app's own OS entry points (`claude://code/new?q=…`,
  `claude://code/continue?session=local_…`), a clipboard paste, Return and Esc — the owner's own gestures.
  A link is handed over ONLY in the app's own session (its bus and keyring, from its own process): under a
  bare `docker exec` environment the hand-off emptied the app's whole cookie store (DGO-1684). It holds no
  credential and takes one call at a time (a second call meanwhile is refused, 409 `locked`, never queued
  behind it). It presses Return only into a composer that holds exactly the text, on the page the app's
  own log says is that session's (409 `not-focused` otherwise), never sends twice, and reports a delivery
  only once the app wrote it; a call answers within ~150 s (`not-confirmed` = Return was pressed but the
  app's files do not show it yet, `unknown` = no answer: look at the app before sending again).

What that means for a caller:
- `new` opens the session in the app's default folder (a scratch folder; the office is reached through the
  brief and the additional directory). A `folder=` from outside makes the app ask "Trust this workspace?",
  and that click is the owner's, so the CLI never asks for one.
- While a call runs the app's screen switches to that session: that IS the proof it is the app's.
- `bbox agent new` first creates a session and then sends its text; the app has no blank session, so the
  first answer is a `pending-…` id and the first message answers with the app's id.
- `send` goes only to a session that is idle (or has no Claude Code process). One that is mid-turn is
  refused with 409 `busy`. One whose live status is `waiting` is refused with 409 `waiting`: a question or
  an approval is open on the owner's screen, where the composer's click and Return would land on its
  buttons. A waiting session lists as running, with `waiting_for`, and its turn is not closed while he
  answers. `bbox agent wait`, then send. Likewise when the composer holds a draft of the owner's
  (`not-sent`): nothing of his is sent or erased.
- `cancel` presses Esc only into a running turn: never into a session waiting on the owner (Esc would
  answer him), never while another session runs (Esc goes to the page on screen).
- A retry of `bbox agent new`'s first message on the same `pending-…` id starts a session again only
  when the first try pressed nothing. After `not-confirmed` or `unknown`, it gets the same answer.
- Not over agent.v1 yet (501, do it on the screen): steer, files, rename, model, fork. Goals, subagents
  and the command list answer empty.

The capability is named `claude-agent`, not `office-agent`: the office agent is whichever app declares
`office-agent`, picked first by path — and `apps/bina-claude` sorts before `apps/bina-ds`, so the same
name would have moved every plain `bbox agent` call from Azaria to Claude. It is reached by id instead:
`--app bina-claude`.

## Both ways

- Azaria → Claude: `./bbox agent --app bina-claude new -F "…"` from bina-ds's shell (inside a container
  the door is the service, `http://bina-claude:3091`).
- Claude → Azaria: `./bbox agent list|new|send …` from a desktop session — it has the checkout and the
  engine's socket, like bina-ds.
