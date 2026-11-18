---
title: The architecture
description: How an office is built — layers 0 to 3, the compiler that turns declarations into a running office, and the contract every app signs.
---

## The problem

An office runs dozens of apps on one computer.
Each needs an address, a sign-in, secrets, data and a place in the start order, and some need each other.
Whoever wires all this by hand gets a system nobody knows how to build again.

## The idea, layer by layer

### The folder is the layer

- `platform/` is layer 0: the compiler.
- `platform-base/` is layers 1–2: what every office gets.
- `apps/` is layer 3: one folder per app.

An app declares itself in an `app.json` file.
The compiler turns the declarations and the office's state into the `.generated/` folder, Docker Compose runs what was generated, and Traefik is the door.

### From the download to a running office

What happens from the moment you run `git clone` and `./bbox run` until the office works:

1. `bbox` loads `scripts/lib.sh`. On macOS every command passes into the engine (Lima), and on Windows `bbox.cmd` passes it into WSL.
2. Admission: the office's branch, the engine, one place for heavy work (a lock and a memory floor), and disk.
3. The `.env` file and the secrets are ready, and then `platform/manager/reconcile.py render` compiles.
4. The compiler loads every `app.json`, loads the state, checks, **resolves** (which apps are on, which app gives each capability another needs, and in what order) and **writes** `.generated/`: one compose file that includes every app's compose in order, the routing labels, the connections, the lists the centre reads, the agents' context, and the plan for the apps that move between linked offices.
5. For each app: `hooks/prepare`, then `docker compose up --wait`, then `hooks/refresh` and `hooks/onboard`.
6. «App Management» (`app-management`) completes what is left, and the run prints its problems.

### The contract every app signs

The schema: `platform/schema/app.schema.json`.

| Field | What it does |
|---|---|
| `id`, `layer`, `kind`, `people` | The identity; where the app may live; `people: admins` puts the administrators-only door on its addresses |
| `capabilities[]` | What it **gives**: a named capability, with an address or an interface (its API) and its actions |
| `use[]` | What it **needs**: a capability, how strongly (`requires` pulls in a provider, `wants` does not), and in what order |
| `routing[]` | The addresses, the ports and the sign-in (`sso`, unless said otherwise), and `module`: its tile in the centre |
| `compose`, `connections[]`, `data`, `health`, `agent.context` | The services; the secrets it registers; the volumes; the check; its brief for the agent (`AGENT.md`) |
| `hooks/<verb>` (files, not a field) | Its command line: `bbox <app> <verb>` runs `apps/<id>/hooks/<verb>` |

### The state

- `platform.state.default.yaml` is the product's default: 17 apps on.
- `platform.state.yaml` is one office's choice: which apps are on, and what comes from linked offices.
- `.env` holds settings and secrets. `BUSINESS_NAME` is the one line a new office edits, and the rest derives from it.

### Four channels

Every app is asked to give four channels: a **screen** (an address and a tile), a **command line** (`hooks/`), an **API** (a capability with an address), and an **event stream** (`dgo:flow:<app>`).
As of 10 November 2026: 57 apps have a screen, 60 a command line, 48 a declared API and 18 an event stream. 15 of 70 have all four.

### What every office gets: the base

| Unit | Name | What it is |
|---|---|---|
| `traefik` · `https-redirect` | Edge router | The edge on ports 80 and 443 |
| `forward-auth` · `authentik` | Identity and sign-in | The sign-in. `forward-auth` has been the default since October, and `authentik` stays as a fallback |
| `postgres` · `redis` | Database · cache and queues | One shared Postgres and one Redis: cache, queues, locks and the event stream |
| `connections` | Connections | The vault of secrets, and a broker that knows who is asking |
| `app-management` · `containers` | App Management · containers | Installing, turning on and turning off — through the compiler |
| `console` | Console (the centre) | The shell: a tile for each app, each app at the address `/a/<alias>/` |
| `bina-ui` | UI library | The one palette («Olive Grove») and the shared components |
| `machine` · `security` | Machine · Security | The computer's data; the door's log (on server offices) |
| `notifications` · `glitchtip` · `autoheal` | Notifications · error tracking · self-healing | Notifications; error tracking (off by default); restarting a container that went down |
| `data-management` | Data management | Backup and restore |
| `follow-runner` | Following the stable version | Takes the new green version of the branch in `DGO_FOLLOW` every 30 minutes |

## What this makes possible

- A new app is a folder with an `app.json`. The compiler finds it a place, an address, a sign-in and secrets.
- The same declaration builds the same office on any computer, so an office can be brought up again from the repository and a `.env` file.
- The capabilities an app gives and needs are written in its file, so you can see what depends on what without reading code.

## Going further

- [The concepts](/en/concepts)
- [The apps](/en/apps)
- [The command line](/en/reference/cli)
- [Several computers — one office](/en/idea)
