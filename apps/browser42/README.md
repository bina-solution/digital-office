# browser42 — the office browser

One Chromium for the whole office, signed in once by the owner: agents drive it over CDP, people watch
and use it in the live view. How to use it is in [AGENT.md](AGENT.md); what it is made of is below.

## What runs here — every piece in one line (DGO-1921)

**Containers**

| container | what it does |
|---|---|
| `browser42-browser` | the one Chromium (cloakserve) on a virtual screen, the live view, and the helpers below |
| `browser42-mcp` | the Playwright MCP door for agents (`@playwright/mcp`, pinned in `Dockerfile.mcp`) |
| `browser42-task-runner` | the agent door `:8766` (`bbox b42 task`, other offices): runs `group-manager.py`, one work command at a time |
| `browser42-reaper` | caps and dedupes tabs, decides when the browser sleeps, writes the open tabs down and reopens them |
| `browser42-task-watchdog` | marks a task nobody drives as stalled and tells the owner; prunes old task records and MCP output |
| `browser42-caddy` | the app's edge: `/view`, `/websockify`, `/handoff`, `/mcp`, `/v1/*`, each behind the gate |

**Inside `browser42-browser`** (`start-browser.sh`; every helper runs under `keep`, which starts it again
when it exits, and every loop starts with `set +e`)

| piece | what it does |
|---|---|
| Xvnc | the virtual screen and its VNC server, one process |
| fluxbox | the window manager (no wallpaper dialog: the image's `fbsetbg` is `/bin/true`) |
| websockify | noVNC — the live view — on `:6080` |
| `localhost-forward.py` ×2 | `*.localhost` on loopback → Traefik; and CDP, broker, noVNC, hand-off → browser42's own network |
| `browser42-broker.py` | the bridge between `group-manager.py` and the tab-group extension (`:8765`) |
| `handoff.py serve` | Caddy's gate and the hand-off link (`:8767`) |
| cloakserve | launches Chromium on the persistent profile and serves CDP on `:9222`; patched only by `patch-cloakserve.py` |
| loop: Xvnc watchdog | Xvnc gone → the container restarts (nothing can draw without it) |
| `browser42-window.py` | sets compact (Chrome's own fullscreen, what F11 toggles) or standard as a state, over Chrome's own DevTools port |
| loop: the window | makes a new window compact once (not one the hand-off made standard); keeps a non-fullscreen one fitted and maximized; closes extra windows once, when the first appears within 5 minutes of boot |
| loop: CDP watchdog | a Chrome alive whose CDP stopped answering for 60 s → the container restarts |
| loop: idle sleep | Chrome exits gracefully after the idle limit the reaper decides; the next use wakes it |

**What it writes, and what removes it**

| where | what | removed by |
|---|---|---|
| `/profile` (volume `cloakprofile`) | the owner's profile — sign-ins, cookies, saved passwords. The app's declared state (app.json `data`): the office's backup carries it, like every app's | never (`bbox b42 state reset --yes` is the owner's) |
| `data/browser42/profile-snapshot*`, `archive/profile-snapshot-*` | **written by nothing since 2026-11-24** (DGO-2188). Copies of the profile an earlier `start-browser.sh` made every 30 minutes (its §4h says what that cost); whatever an office still holds is left where it is | a person: `cp -a <copy>/. /profile/__default__/` into a stopped browser brings one back; removing them is the owner's |
| `data/browser42/tasks/<slug>` | a task's record, journal and evidence | the watchdog, 14 days after its last write (`BROWSER42_TASK_KEEP_DAYS`) |
| `data/browser42/output` | the MCP's console logs and files | the watchdog, after 7 days (`BROWSER42_OUTPUT_KEEP_DAYS`) |
| `data/browser42/groups`, `handoffs` | a group's manifest; a hand-off's state | `bbox b42 close` / `gc`; the hand-off's end |
| `data/browser42/.activity`, `.sleeping`, `last-tabs.json`, `settings.json` | idle sleep's markers, the open tabs, `sleep after N` | rewritten in place |
| `/tmp/b42-run-<pid>-*` (runner, browser) | one `group-manager.py` run's temporary files (Playwright's) | the next run, once that process is gone |
| container logs | every container's stdout/stderr | Docker's rotation, 10 MB × 3 |

**Files**: `group-manager.py` (every verb: groups, tasks, tabs, hand-off opens), `handoff.py`, `logins.py`
(Chrome's password store ↔ the credential plane), `reaper.py`, `task-runner.py` + `task-client.py` +
`remote-task.py` (the agent door, its local client, a linked office's), `task-watchdog.py`,
`patch-cloakserve.py`, `browser42-state.sh` (encrypted dump/load of the profile), `extension/` (tab groups and
the agents' cursors), `browser-*.js` + `viewer/` (the live view's toolbar, clipboard, phone keyboard and
its "screen down" card), `caddy/Caddyfile`, `hooks/` (the `bbox b42` verbs), `operatives/` (page, shot).

## The human hand-off (DGO-571)

When the office browser needs a person — a captcha round that three
clicks did not pass, a sign-in only the owner can do — every escape path carries ONE address instead of
a generic "open the live view": `bbox b42 handoff <slug>` prints it, the `captcha_attempts_exhausted`
refusal names it, and the owner gets it in the office's notice centre (`notifications:8977`, source
`browser42`, one notice per slug and per episode). The address is a console deep link,
`<console>/a/browser42/handoff/<slug>` (built from `CONSOLE_BASE_URL` + `AUTH_PROTOCOL`, the way a
project-pln work item's link is); opening it reaches `handoff.py` (:8767 inside `browser42-browser`,
only through Caddy's `/handoff/*`, which adds the token the route requires, and the app's
`/a/browser42/handoff` passthrough in `app.json`), which wakes the browser the one way
(`/json/version`, one launch at a time — a request that waited 20 s gets a "waking…" page that reloads
into the same launch), brings that group's tab to the front through the extension broker (action
`front` — the same window, never a new one; after an idle sleep the extension finds the tab again by
its last address and re-tags it), leaves compact presentation (F11) so the tab strip and the group's
name on it are visible, and lands on the live view. A tab it could not bring to the front is said, not
pretended: the view opens with `?lost=<slug>` and the viewer's status line names it. A **stalled** task
is different: the watchdog releases its tab (the reaper would reap a terminal task's tab anyway), so its
notice says so and links the live view, promising no tab. The limit, stated plainly: noVNC shows a
whole **screen**, not a tab, so the promise is "the right tab in front with its group named on the
strip" — the person still sees the other groups' tabs beside it.
