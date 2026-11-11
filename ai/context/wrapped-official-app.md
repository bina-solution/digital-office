# A wrapped official app: the vendor's own client, as an app of the office

How the office brings in an outside product. It wraps the vendor's OWN client rather than re-making it:
- the vendor's Linux client is the screen;
- the vendor's own headless side sits behind the CLI and the API;
- one volume keeps the sign-in.

Written 2026-11-10 for DGO-1259, from the two wraps that run: bina-claude (Claude Desktop) and cad (FreeCAD).
The rule each wrap keeps is ai/context/app-cli-api-standard.md §6, and gate G108 (wrapped-app-lint) holds it.
The catalogue of the next candidates is on DGO-1265: Telegram, Obsidian, Signal, Slack, Discord, Element.
The starting files are in `apps/_template-wrapped/`.

## Why wrap, and not re-make

A vendor's client is the product people know: its screens, its sign-in, its updates.
- Re-making it in the office (an API client with a screen of our own) costs months, and is always behind.
- Wrapping it costs one image. The office adds what the vendor's client lacks:
  - one sign-in;
  - a tile in the console;
  - a CLI and an API that agents and automations can call;
  - an event stream.

## The four channels of a wrap

| channel | what it is in a wrap | bina-claude | cad |
|---|---|---|---|
| **screen** | the vendor's Linux client in a desktop streamed to the browser, under the console's tile | Claude Desktop under Selkies (`Dockerfile.desktop`, service `bina-claude-desktop`, routing `module` with `embed: true`) | FreeCAD in linuxserver's image (`apps/cad/docker-compose.yml`, routing `module`) |
| **cli** | verbs in hooks/ over the headless side | `ask`, `sessions`, `show`, `status`, `signed-in`, `session` | in `cad-api` (`takeoff`, `verify`, `model`, `families`) |
| **api** | the headless side behind a contract: a capability with an `interface` and an `endpoint` (G108 also takes an app's own `/api` routes) | the adapter (`adapter/server.mjs`) speaks agent.v1 at `http://bina-claude:3091` | cad-api's `/api` routes; it declares no capability yet |
| **flow** | hooks/flow, publishing through `platform-base/redis/flowpub.py`. G108 counts the hook, not the publisher, so the hook goes in only with a publisher behind it | not yet (G108 KNOWN) | not yet (G108 KNOWN) |

Declare it in app.json, so the gate holds it:

```json
"wraps": { "client": "<the vendor's client, and where it comes from>",
           "headless": "<the vendor's CLI or library, or 'none'>",
           "headless_app": "<the app that carries the headless side, when it is its own app>" }
```

## The screen: the vendor's client, streamed

- **Selkies, not VNC** (bina-claude's `Dockerfile.desktop` header, DGO-1074).
  - Selkies streams H.264 that the browser's WebCodecs decode, over one websocket, so it passes Traefik and
    the sign-in like every app.
  - It follows the window's size, keeps the clipboard both ways, moves files, and takes phone touch and IME.
  - noVNC (browser42's stack) sends lossy JPEG and a text-only clipboard.
- **The base image** is `ghcr.io/linuxserver/baseimage-selkies`, pinned BY DIGEST, as bina-claude's is.
  linuxserver publishes no `latest` and breaks between versions. No gate checks that a Dockerfile's `FROM`
  line is pinned (G15 reads compose files), so the pin is the line's own discipline. cad is not on this base: it runs
  linuxserver's FreeCAD image, pinned by tag only (`apps/cad/freecad/Dockerfile`).
- **The vendor's package** comes from the vendor's own repository, its signing key checked against the
  fingerprint the vendor publishes (bina-claude: Anthropic's apt repo, `Dockerfile.desktop:26–36`). Never a
  copy of the binary, and never a third-party build of it.
- **The sign-in lives in the desktop's keyring** (GNOME Keyring + the session bus). Without an unlocked one
  the client asks again on every launch. The keyring sits in the ONE volume the app keeps.
- **Fonts for Hebrew and emoji** (`fonts-noto-core fonts-noto-color-emoji culmus`).
- **The tile** is a routing entry with `auth: "sso"`, an `sso` block (slug, display name, default host,
  `base_url_env`, `local_twin`) and a `module` with `embed: true`. Without the `sso` block the compiler emits
  no sign-in provider for a layer-3 app (`reconcile.py`, «not ours to invent»): the edge routes the tile and
  the sign-in answers 404. Gate G20 (sso-provider-lint) catches the omission. The stream's websocket goes through `passthrough` with `transport: "websocket"`.
- **A front door** (bina-claude's `adapter/gate.mjs`, run by `desktop/svc-bina-gate`) stands in front of
  the stream. The stream listens on the container's loopback, and the door admits a connection only from the
  addresses the office's own DNS gives the edge, the console and the link proxy. An identity header proves
  nothing, since any container on the network can forge one; an address on the bridge cannot be forged.
  A screen of a signed-in client must not be open to every container, so the door is not optional. A new wrap
  copies gate.mjs (an app never reaches into another's folder); a door shared from platform-base would be
  one copy for all of them, and is not built yet.

## The headless side: the vendor's CLI or library, behind a contract

- The vendor's own headless side. For Claude it is Claude Code. For Telegram it would be TDLib, and for
  FreeCAD `freecadcmd`.
  - It runs where the client's sign-in is: the same volume, or an app of its own (`headless_app`).
- An **adapter** turns it into a contract the office already speaks: agent.v1 for an agent, chat.v1 for a
  messenger, a capability's `required_ops`.
  - Callers use the contract, never the vendor's protocol.
- **hooks/** are the CLI. Each verb is one call to the adapter's API, following the standard: `--json`,
  exits 0/1/2/3, secrets on stdin.

## The volume, the data and the rest

- **One volume** holds the client's home, its sign-in and its data: `data.volumes`, `on_uninstall: keep`
  (bina-claude). The desktop mounts its `desktop` folder as HOME and the adapter mounts the root, and a one-shot
  service makes the folder first, with `nocopy` (bina-claude's compose says why). cad keeps two volumes.
- **Health** probes the adapter (`health.probe.http`), and the desktop has its own healthcheck in compose
  (bina-claude). cad probes its desktop.
- **The desktop's memory**: `shm_size: 1gb`. Chromium and Electron renderers share memory through /dev/shm,
  and docker's 64 MB default crashes them. Every service has its caps and its log rotation.
- **The brief** (AGENT.md) says what the client can do, where its sign-in lives, and what an agent may do
  through it.
- **Docker inside**, only when the client must drive the office (bina-claude's sessions do): the CLI pinned
  to the engine's version (`docker-ce-cli=5:28.5.2`, bina-claude's `Dockerfile.desktop`), with the socket's
  group joined at start. Gate G74 holds the compose plugin's version and a `docker:<engine>-cli` copy stage,
  not this apt pin.

## The check before a wrap enters the catalogue

1. app.json declares `wraps`, and `python3 scripts/refactor/wrapped-app-lint.py` passes with no KNOWN line
   added.
2. The vendor's package comes from the vendor's repository, its key fingerprint checked, the base image
   pinned by digest.
3. The sign-in survives a restart of the container (the keyring in the volume).
4. The tile opens the client on a phone and on a desktop, and a stream that does not connect shows the
   office's card, never a raw error (DGO-437).
5. Every verb of hooks/ answers `--help` and `--json`, and a wrong call exits 2.
6. The headless side answers the contract's `required_ops`.
7. What the client does is published on `dgo:flow:<app>`.

## Traps, each met once

- **Docker 29 fails silently** (running-the-stack.md). The CLI inside is pinned to 28.5.2 and the compose
  plugin to the host's version: a different one hashes services differently and recreates them.
- **A client's Recommends** may pull what a container cannot run. Claude Desktop's are QEMU/OVMF for
  Cowork, which needs /dev/kvm. Install with `--no-install-recommends`, and say why in a comment.
- **The client's own updater** must not replace the binary inside the image. The image is the version, and
  a bump is a rebuild.
