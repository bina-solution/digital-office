# bina-claude — «בינה קלוד»

Claude Code inside the office (DGO-1074). The owner, 2026-10-31: «focus on having just the Claude
inside and fully controllable via CLI, API, and UI … so it can be used from Azaria, from Bina DS … Claude
will be able to use Bina DS's agents, same thing, via the CLI».

## What it is

Two containers on one volume (`bina_claude_home`):

| Face | What | Where |
|---|---|---|
| UI | **the official Claude Desktop app for Linux** (apt `claude-desktop`), streamed by Selkies | the console tile «בינה קלוד», `/a/bina-claude/` (service `bina-claude-desktop`) |
| Terminal | Claude Code CLI (npm, pinned) in a web terminal (ttyd) on one tmux session | the tile «בינה קלוד · מסוף», `/a/claude-terminal/` (service `bina-claude`) |
| API | agent.v1 ([agent-contract.md](../../ai/context/agent-contract.md)) | `http://bina-claude:3091` in the office network; `127.0.0.1:3091` on the docker host |
| CLI | `./bbox bina-claude status\|ask\|attach\|sessions\|show`, and `./bbox agent --app bina-claude …` | any shell of the office, any agent |

## The desktop app, natively (Selkies)

The owner, 2026-10-31: «I want everything to be natively like I installed the software … native Docker
for Linux containered and served like I serve browser 42 … I'm not sure if VNC is the best way».

The app is installed exactly as Anthropic's Linux docs say (their apt repository, key fingerprint
checked in the build) on linuxserver.io's `baseimage-selkies` (Debian trixie, X11 mode), and runs as the
image's user `abc` with HOME `/config` = the volume's `desktop` folder, so its Claude Code sessions are
office data (`./bbox bina-claude sessions`). Its sign-in is kept in a GNOME keyring unlocked at every
start (`desktop/autostart`), so it survives recreates.

Why Selkies over VNC (research on DGO-1074): H.264 decoded by the browser (WebCodecs) over ONE websocket —
no UDP or TURN, so it passes Traefik + SSO like every app — resize to the browser window, a pinned DPI
(`BINA_CLAUDE_DESKTOP_DPI`, 96–288), clipboard both ways with images, file upload/download, phone touch
and IME input. noVNC (browser42's stack) sends soft JPEG text and a text-only clipboard. Not available
in a container: Cowork (it needs `/dev/kvm`).

**The stream needs a secure context.** The browser decodes it with WebCodecs, which a page served over
plain HTTP from a non-localhost name refuses ("FATAL: Not in a secure context. WebCodecs require
HTTPS", measured 2026-10-31). `console.localhost` (the Mac) and an HTTPS office (vps1) are secure; an
office opened at a LAN IP over HTTP is not, and shows the sidebar without the picture.

The front door is the terminal's (`adapter/gate.mjs`, an s6 service here): the image's nginx is moved
to the container's loopback (:3100) at build, and :3000 admits only the edge and the console.

Measured on the Mac (2026-10-31): claude-desktop 4.4212.0, Selkies 2.1.0 (websockets, x264 on the CPU),
the container at ~400 MB, the app at ~11 % of a core when idle.

### The office, in every desktop session (DGO-1275)

The owner: «It should by default have the digital office directory the hp has like azaria gets in
bina-ds». The app's Code sessions get the office with nothing chosen by hand:

- the checkout is mounted in the desktop container too, and `/workspace/office` points at it (the
  launcher keeps the link; `/workspace` is the desktop user's in the image); the app is started there;
- its `~/.claude/CLAUDE.md` is the office brief, written by `entrypoint.sh` into BOTH homes (the
  terminal's and the desktop's, `/data/desktop`): it is inside the DGO, the office is
  `/workspace/office`, read `AGENTS.md`, and — the desktop has no docker — `./bbox` runs in the terminal tile;
- its `~/.claude/settings.json` has `/workspace/office` in `permissions.additionalDirectories` and
  `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1`, MERGED into whatever the app and its owner keep there:
  every session reaches the office and loads its own CLAUDE.md/AGENTS.md, whatever folder it opened in.

What is not a setting: the folder a NEW Code session opens in. Claude Desktop documents no default
folder (code.claude.com/docs/en/desktop), so a session the app opens in a fresh folder still sees the
office through the brief and the additional directory. The app offers the folders used most in the last
month as its environments, so `/workspace/office` joins that list once it is chosen.

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

The terminal tile stays the serving office's own: the link strips identity headers, and ttyd requires
one. The stream needs a secure context, and vps1's HTTPS console is one.

## Every session, everywhere — Remote Control

claude.ai itself cannot live in a frame here (`X-Frame-Options: SAMEORIGIN`). To have the office's
sessions ALSO in claude.ai/code and the Claude apps on other machines, use Claude Code's **Remote Control**: after signing in, type `/remote-control` in the terminal
(or run `claude remote-control --spawn worktree` there, the server mode). This office's sessions then
appear at claude.ai/code and in the Claude apps (desktop, phone) beside all the owner's others, and a
session started THERE runs HERE, on the office checkout. It needs a claude.ai login (not an API key),
outbound 443 only, and a terminal for its one-time "Enable Remote Control?" question — the tile is that
terminal. `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` must stay unset: it switches Remote Control off.

Remote Control is started by the owner, not by the container: it opens a door from his Claude account
into a root shell on the office, and that is his decision to make (an automatic start was refused by
the session's safety check, 2026-10-31). Sessions made through the API (`claude -p`) are not
attachable to Remote Control; they are visible through agent.v1 only.

## Signing in

Open the tile and type `/login` in Claude Code: it shows a link to claude.ai; sign in there and paste
the code back. The credentials land in `~/.claude/` on the app's volume (`bina_claude_home`, HOME is
`/data/home`), so they survive recreates, and the API's turns use the same account. Check with
`./bbox bina-claude status`.

An API key instead of the account: `BINA_CLAUDE_ANTHROPIC_API_KEY=` in `.env`. The office's own
`ANTHROPIC_API_KEY` is deliberately not forwarded — Claude Code prefers a key over the login, so it would
silently bill the API instead of the subscription.

## The API

A session is a record of the adapter plus the Claude Code session it resumes. Each message is one
`claude -p … --output-format stream-json --verbose --resume <id>` run, translated into the contract's
events, so `bbox agent follow` renders Claude's tool calls and text exactly as it renders Azaria's.
State is on the volume: `/data/bina-claude/sessions/<id>.json` (summary) and `.jsonl` (events).

The capability is named `claude-agent`, not `office-agent`: the office agent is whichever app declares
`office-agent`, picked first by path — and `apps/bina-claude` sorts before `apps/bina-ds`, so the same
name would have moved every plain `bbox agent` call from Azaria to Claude. It is reached by id instead:
`--app bina-claude`.

Implemented routes: health, sessions (list/create/get), messages (send/list, steer), events (SSE),
cancel, rename, model, models, presets, permissions, search, and `GET /v1/login` (which account).
Not implemented: goals, subagents and the command list answer empty; upload, fork, command and preset
answer 501 (so `bbox agent --app bina-claude new -f <file>` refuses — put the file in the checkout and
name its path). A turn cut by a restart of the adapter ends with `turn.end {reason: "interrupted"}`.

## Who can open the terminal

The terminal is a root shell with the engine's socket. ttyd listens on the container's loopback
(:7682); the only door is `adapter/gate.mjs` on :7681, which admits a connection only from the
addresses the office's DNS gives the edge and the console (`BINA_CLAUDE_TERMINAL_PEERS`, default
`console traefik-deployment traefik-<DEPLOYMENT_NAME>`); everyone else gets 403. The identity header
alone was not enough: any container on traefik-network can write one, but none can connect from
another container's address.

Settings (`.env`): `BINA_CLAUDE_MODEL` (opus|sonnet|haiku or a full id; empty = the account's default),
`BINA_CLAUDE_MAX_TURNS` (turns at once, default 2 — each is a ~250 MB process),
`BINA_CLAUDE_PERMISSION_MODE` (default `bypassPermissions`, the same full access bina-ds has).

## Both ways

- Azaria → Claude: `./bbox agent --app bina-claude new -F "…"` from bina-ds's shell (inside a container
  the door is the service, `http://bina-claude:3091`).
- Claude → Azaria: `./bbox agent list|new|send …` from Claude's shell — it has the checkout and the
  engine's socket, like bina-ds; from a container the local office agent is reached at its service.
