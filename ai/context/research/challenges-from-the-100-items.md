# DGO — the challenges, as the last 100 work items state them (DGO-491…591, read 2026-10-14)

Each row: the challenge · how it is implemented today · what the items measured · the owner's bar
(minimal dependencies · max security · zero duplication · minimal coupling · simplicity · generality ·
zero feature loss · minimal bytes).

## A. One product on every machine (Windows / macOS / Linux / Android / a VPS)

| Challenge | Today | Measured in the items | Gap against the bar |
|---|---|---|---|
| A first run from a download, no git clone | `bbox.cmd` → WSL, `./bbox` → Lima on macOS, git clone + python3 + PyYAML + 10–15 min image build | DGO-588: dgo-install 5.2 MB (over the 5 MB target), no signing key, no manifest host; core-005 step 1 not landed | the host needs Python before the core exists; three hand-offs (cmd → wsl → bash) each with its own failure (0x8007274c all evening) |
| The engine substrate | Docker CE 28.x pinned inside WSL / Lima; Docker 29 breaks traefik 3.3 silently | CLAUDE.md caveat; baseline P0 fails fast | layer 0 depends on a container engine it does not own; traefik's client API 1.24 is a hidden version coupling |
| Android | nothing yet | research 2026-10-14: no Docker unrooted; Go static binary runs in Termux; stdlib DNS and `net.Interfaces()` broken on Android without patches | "office in your pocket" is layer 0 only (identity, link, notifications, console) — must be promised as such |

## B. Many offices, one owner (the link)

| Challenge | Today | Measured | Gap |
|---|---|---|---|
| A pair that survives until unpaired | WireGuard in a container (`dgo-net`), pairing by two codes (offer/reply/confirm), a link door (`link-proxy`) routing by Host, a catalog pulled every minute, projection into `platform.state.yaml` `remote:` | DGO-555: 13 death modes — DHCP address change (lnk-017), source-port wedge, netns death on rebuild, sleeping office, silent record drop (DGO-554), wrong dial direction (DGO-557), two tunnels on one /24, 409 dead-end on re-pair (DGO-553) | the tunnel holds alone; the RECORD does not — too many writers of the pair's truth (host wg-quick + container tunnel + yaml + .env + catalog) |
| Identity across the link | the door signs `x-dgo-identity` (HMAC, pair secret, 300 s) — DGO-545; Plane accepts it; agent doors need a vault token handed over by `converge._handoff_agents` through SSH | DGO-581/589/590/591: a PAIRED pair has no handoff channel (`machine: null`), browser door unpublished (`agent_api_port` None), a UI door answering 200-empty for every path | identity is header-based inside the office network; secrets handoff rides on a machine channel the pair does not have |
| One browser, driven from anywhere | browser42 on HP only (owner's decision, DGO-568/579), MCP on 8931 behind a token, task-runner on 8766 with NO authentication (issue 94cbde88) | DGO-570: the uniform door exists in principle; the verifier must come before the door | a second browser was raised by accident (DGO-579) because `apps enable` does not know what a link already serves |

## C. The autonomous agent as an app (bina-ds / עזריה)

| Challenge | Today | Measured | Gap |
|---|---|---|---|
| Continuous work with a cost ceiling | goals + rounds in the harness; the pulse (deleted on vps1, alive on HP) re-armed goals; cost-meter displays only | DGO-539: $4.92 in a night, 792k-token requests, `pause` did not hold, a `complete` goal revived with 400 rounds; DGO-559: 31.8 min / 457 tool calls for one bug report | no resource budget anywhere in the loop; context length IS the bill (one item per session is the fix) |
| A daily shape | the seder (3 cycles, 8 named steps, ₪1/day), n8n `binaSeder00001` → `POST /v1/seder/<cycle>` on the adapter | DGO-560…563, 585, 586 implemented on vps1; DGO-565: the door opened 11 real cycles from a harmless probe; DGO-582: a cycle died with the container and nobody knew | the door had promises in comments the code never kept; no record on container exit (`harness` is PID 1) |
| Where the agent lives | the container restarts in place (exit 0, no log) — DGO-564; self-update from the host bypassed the snapshot door — DGO-550 | fixed on vps1 (supervisor, patience window), not on HP | the agent's runtime is a container that can die mid-turn; sessions must be durable by design, not by luck |
| What the agent is told | AGENTS.md + CLAUDE.md both injected (7.2k tokens), per-app briefs 27.5 KB → ≈23k tokens before the first word | ai/context/agent-context-cost-2026-10-13.md; proposal AZARIA.md + DGO.md ≤8k | duplication of instruction files = tokens every session |

## D. The UI (one shell, every app, every screen size, Hebrew RTL)

| Challenge | Today | Measured | Gap |
|---|---|---|---|
| Link = state, every screen addressable | shell grammar `#/m/<id>[/inner][?r=]`, `bina-route.js` block, G83 | DGO-501: 13/14 apps route; DGO-569: remote tiles excluded from the gate, no http→https redirect on nested hosts | frames of frames: the shell cannot read a cross-origin frame; the console proxies every app (`/a/<alias>/`) |
| Phone | profiles 390/834/1366, desktop-mode windows down to 380×260 | DGO-536 keyboard covers input; DGO-551/552 menu squeezes; DGO-574 Plane pans sideways (UA-decided layout); DGO-576 the map measured with a desktop UA | third-party apps (Plane) decide by user-agent; our profiles had no UA |
| One palette, one copy of each block | theme-tokens.css + G27/G82; bina-ui blocks stamped into carriers | 5 copies of the table/modal before G27 (DGO-528, 518/519) | the simulation is a second UI that drifts (DGO-525/527) |

## E. The data and state layer

| Challenge | Today | Measured | Gap |
|---|---|---|---|
| One desired state, one writer | `platform.state.yaml` written only by the compiler; `.generated/` rendered; generations/rollback | G33 state-writer-lint; the committed copy is the MAC's set (skip-worktree locally, DGO-408); `.env` clobbered to 43 bytes by a test (DGO-585) | the state file is both a repo file and a per-office runtime record |
| Shared code, three writers, one tree | one checkout per office, commits by path | hp-dgo 102 commits unpushed (no git creds in the agent container), vps1 cannot pull (DGO-549), 47 commits apart | the office's agent cannot publish its own work; offices diverge |
| The blueprint as shared truth | n8n workflows as `*.workflow.ts`; `pull` from a non-canonical instance rewrote the shared blueprint (DGO-558); `push` truncated a jsCode silently (DGO-584) | fixed on vps1 / in progress | no read-back verification after a write to a live system |
| Backups | per-app volumes; backups by app hooks; data-management inventory | Raphael data scan posts when a store is unclaimed/not backed up (DGO-492) | not every store declares its backup |

## F. Quality as a system (gates)

| Challenge | Today | Measured | Gap |
|---|---|---|---|
| 80+ gates, several red on the base | `scripts/ci/gates.sh`, KNOWN_RED, CI matrix | DGO-587: 12 static gates red + 5/20 ci-verify red on vps1; gates die on PermissionError from root-600 files written by the agent | the number of gates grew with every outage; a redesign must retire gates whose rule moves into the type system / compiler |
