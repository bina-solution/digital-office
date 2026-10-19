# Running the stack on Windows

There is **one** way to run this stack on Windows. If you find another set of instructions anywhere
(a different doc, a comment, an old habit) — they are wrong; this is the only path.

```
git clone <repo> C:\path\you\like\deployment-hacohen
cd C:\path\you\like\deployment-hacohen
bbox.cmd run
```

Run it from a normal `CMD` or PowerShell prompt, in the repo directory. That's the whole setup.
`bbox run` brings up a healthy, fully routed stack; see [CLAUDE.md](../../CLAUDE.md) for what to run
against it afterward.

## The words, so nothing below is ambiguous

Docker is two programs, and conflating them is what makes every explanation of this confusing:

| Term | What it is |
|---|---|
| `docker` | The **CLI** — what you type. Does no work itself: it dials a socket and asks an engine. |
| `dockerd` | The **engine** — the daemon that does everything and owns the images, containers and volumes. |
| socket | Just an **address** the CLI dials to reach an engine. |

On this machine there are **two engines**, and they share nothing:

- **the project engine** — the `dockerd` inside the WSL distro `Ubuntu`. Owns every image and volume
  this stack has. **The only engine the stack ever talks to.**
- **Docker Desktop's engine** — a different `dockerd`, in its own distro, with its own images and
  volumes. **Never used.** Installed, running, or absent makes no difference.

A dedicated third engine would buy nothing: it would be equally isolated from Docker Desktop and
start empty, so every image would rebuild and all 32 volumes would need migrating. Two engines also
cannot both publish `:80` for traefik, so it would have to *replace* the project engine — which is
the project engine, minus the data. Not worth it; deliberately not done.

## What `bbox.cmd` actually does

It is a thin forwarder: it resolves the directory it's sitting in to a WSL path and hands the rest of
the command line to the real `bbox` (a bash script) inside the `Ubuntu` distro, running against that
same directory — not a copy, not a clone. Whatever you edit in your `C:\...\deployment-hacohen`
checkout is exactly what `bbox run` builds and serves.

```
bbox.cmd run       ≡ wsl -d Ubuntu -u root -- bash -lc 'cd <this dir, as a WSL path> && ./bbox run'
```

So the "engine" is Linux (WSL2 + Docker CE), but the checkout stays on the Windows drive, in one
place, and there is nothing to keep in sync.

## Why WSL at all, if not for Docker Desktop

Docker's engine is Linux-only. Windows has no native equivalent, so *something* Linux has to run it.
WSL2 is that something — a lightweight Linux VM Windows ships with. Docker Desktop is one way to put
an engine inside that VM; **this project supplies its own instead** (Docker CE via `apt`, pinned to
28.x — see the Docker-29 note in [CLAUDE.md](../../CLAUDE.md)), so Docker Desktop is never required
and, if present, is deliberately not used.

`bbox run` provisions everything the project engine needs the first time it's missing: it installs
nothing by hand and starts nothing you have to remember to stop.

## One host setting, already done, worth knowing about

Windows paths (`C:\...`) are visible inside WSL at `/mnt/c/...`, over a 9p filesystem. By default 9p
reports **every file as `777`** and `chmod` is a silent no-op — which breaks `acme.json`'s required
`600` permission and makes traefik fall back to a self-signed certificate with no error. Fixed once,
system-wide, in `/etc/wsl.conf`:

```
[automount]
options = "metadata,umask=22,fmask=11"
```

`metadata` is what makes real Unix permissions exist on `/mnt/c` at all. It's already set on this
machine. On a new machine, `bbox install windows` checks for it and tells you if it's missing — it
takes one `wsl --shutdown` to apply, which restarts every WSL distro (see the memory note below for
why that's sometimes worth doing anyway).

## Docker Desktop is not ours — verify it, don't assume it

Docker Desktop's WSL integration **binds `/var/run/docker.sock` inside the `Ubuntu` distro** and
forwards it to Desktop's own engine. The distro's real `dockerd` keeps running underneath — it just
loses that socket path. Nothing logs this; it looks identical to success.

So the project engine listens on its own path instead, **`/run/bbox-docker.sock`**, which Docker
Desktop has no reason to ever touch:

- `bbox run` provisions it (a `docker.service` drop-in adding `-H unix:///run/bbox-docker.sock`).
- `scripts/lib.sh` pins `DOCKER_HOST` to it for the CLI and every script.
- Every container that talks to Docker directly (traefik, machine, connections, app-management,
  any-concurrency, portainer) mounts `${BBOX_DOCKER_SOCK}` on the **host** side of its socket bind —
  the container-side path is unchanged, so nothing inside those services had to move.

**Root is a one-time bootstrap cost, not an ongoing requirement.** Creating that address needs root
once. Afterwards the socket is `root:docker` and group-writable, so anyone in the `docker` group runs
the whole stack unprivileged. If you see `cannot provision … (needs root or passwordless sudo)`, that
is the message before the first successful provision — not a separate mode.

`bbox run` has exactly **two** paths here, and the difference is not *which* engine but *whether one
exists yet*: if an engine is already running (VPS, WSL) it is taught the extra address; if none exists
(the cloud sandbox boots without one) it is started. Everything after that is one shared path.

This last point is the one that actually cost a session, measured 2026-07-30:

```
/var/run/docker.sock   OS=Docker Desktop      running=0   images=7
/run/bbox-docker.sock  OS=Ubuntu 22.04.3 LTS  running=39  images=60
```

Opening Docker Desktop re-bound the conventional path. Traefik — which back then still mounted that
path — followed Desktop's engine, found none of this stack's labels, and served 404 for every
`*.localhost` while reporting healthy. Stopping Desktop's stray containers took the whole site down,
with all 39 real containers up and healthy the entire time. It reads exactly like the Docker-29 trap
in [CLAUDE.md](../../CLAUDE.md); it is a completely different cause, reached through the socket mount
rather than the API version.

To check which engine anything is really talking to:

```bash
wsl -d Ubuntu -u root -- bash -lc 'docker -H unix:///run/bbox-docker.sock info --format "{{.OperatingSystem}} running={{.ContainersRunning}}"'
```

`OperatingSystem: Docker Desktop` is the tell that something is pointed the wrong way.
`BBOX_DOCKER_HOST` overrides the endpoint choice entirely, if you ever need to.

### …and it owned the compose binary too

The engine was only half of it. `/usr/local/lib/docker/cli-plugins/` is **entirely symlinks into
`/mnt/wsl/docker-desktop/cli-tools/`** — `docker-compose` among them — and that directory outranks
the distro's. `docker compose` is a plugin SEARCH, so every `bbox run` was executing **Docker
Desktop's** compose (`v2.34.0-desktop.1`) while the plugin this project installs sat unused at
`/usr/libexec/docker/cli-plugins/docker-compose` (`v5.3.1`). It worked, so nothing looked wrong —
but uninstalling Desktop would have dangled the symlink and broken the CLI while the engine, images
and volumes stayed perfectly healthy.

So the stack names its own binary rather than competing for a lookup. Same remedy as the socket, and
no machine tweak: Desktop's symlinks are left exactly where they are and simply not consulted.

## The variables that make this work

| Variable | Set by | Why it exists |
|---|---|---|
| `BBOX_DOCKER_SOCK` | `scripts/lib.sh` | The project engine's own address, which Docker Desktop has no reason to bind. Compose interpolates it into every service that mounts the docker socket. |
| `BBOX_COMPOSE` | `scripts/lib.sh` | The compose plugin **this project installs**, by path. Not `docker compose`, which is a search. |
| `BBOX_REPO_HOST` | `scripts/lib.sh` | The repo's path *as the daemon sees it*. app-management mounts the repo at this same absolute path, so compose's bind sources resolve on the host. Without it compose emits container-side paths to a daemon that has no such directory, and docker CREATES them — as directories. |
| `BBOX_TMP` | `scripts/lib.sh` | Per-uid scratch dir. A fixed `/tmp` path is unwritable by a second user under `fs.protected_regular=2`, and the failure surfaces as a redirect error mid-script. |

## An app brings up its own prerequisites

`bbox run` runs `<root>/<id>/hooks/prepare` for every **enabled** app that has one, over
`reconcile.py enabled-apps`. bbox names no app. This is the bring-up counterpart of the on-demand
`bbox app <id> <verb>` convention — an app declares what it needs by *having the file*, and gets it
whether it is started by the CLI or installed from the apps screen.

Present today: `apps/portainer/hooks/prepare` (its admin password file),
`platform-base/traefik/hooks/prepare` (acme.json mode + ACME contact),
`apps/browser42/hooks/prepare` (its digest-pinned base on a proxied sandbox).

## Converging the estate

`POST /api/reconcile` on app-management brings ACTUAL state up to DESIRED state for every enabled
app: containers declared but absent are brought up, blueprints declared but missing are imported. It
is additive — it never removes or deactivates — and it is safe to call repeatedly.

It exists because the control plane was transition-driven: a data wipe left `platform.state.yaml`
saying `enabled` while n8n held zero workflows, and nothing noticed, because no transition happened.
`bbox status`'s "blueprint clean" could not catch it either — that compares git to the working tree
and never asks the instance. `apps/n8n/hooks/present --app <id>` is the check that can
actually be wrong:

```bash
bash apps/n8n/hooks/present --app indox   # -> 70/70, exit 0
```

Exit 0 present, 1 missing, **2 cannot tell** (n8n down / no blueprint declared). The third is not the
second: treating "cannot tell" as "missing" would import against a half-started instance.

Full findings, phase history and what is still open: [platform-os-consolidation.md](platform-os-consolidation.md).

## The daemon is systemd-managed — never start `dockerd` by hand

This distro has `systemd` (`/etc/wsl.conf` sets `[boot] systemd=true`), and `docker.service` owns the
daemon. **Never** run `dockerd` yourself, even to "fix" something — a second daemon against the same
`/var/lib/docker` corrupts it. `bbox run` provisions and starts what it needs.

```bash
wsl -d Ubuntu -u root -- bash -lc 'systemctl status docker --no-pager | head -5'
```

## Everyday use

```
bbox.cmd status
bbox.cmd baseline
bbox.cmd indox test all
```

All forward the same way. Everything is reachable from Windows exactly as if it ran there natively —
`console.localhost`, `n8n.localhost`, all of it — because WSL2 forwards localhost, so traefik on `:80`
inside the distro answers the Windows browser directly.

## One memory-tuning decision worth knowing about

`C:\Users\user\.wslconfig` caps the WSL VM's memory. The project engine now runs the *entire* stack
inside that VM (not just a thin Docker Desktop layer), so during a heavy operation (e.g. `bbox
baseline`) the Windows side can drop close to its limit, and `wsl.exe` starts returning

```
Error code: Wsl/Service/0x8007274c
```

— a timeout talking to the VM, not a failure inside it. Anything scripting the stack from Windows
should treat that as "unknown, retry", not "the command failed".

WSL2 also does not hand memory back to Windows as processes inside it exit — the VM holds its
high-water mark. If a heavy run leaves Windows short on memory afterward and it doesn't recover on
its own, `wsl --shutdown` reclaims it instantly. That stops everything in every WSL distro, so do it
at a checkpoint, never mid-run.

## Can another office dial this one? — WSL's networking mode

Everything above works in either of WSL's two networking modes. One thing does not: an office that
another office DIALS (a paired office that listens for its tunnel — `apps/dgo-extend`) must be
reachable on one UDP port from the network, and under WSL's default **NAT** mode nothing on the
network reaches the distro at all. Such an office can only dial; its own screen says so, with why.
In **mirrored** mode the distro shares the machine's interfaces and ports, `bbox run` declares the
machine's LAN address by itself and `bbox.cmd` opens the port in the firewall (one consent prompt).

```
bbox.cmd dialable -Check     # which mode is this machine in? (reads only)
bbox.cmd dialable            # switch to mirrored: says exactly what it will do, asks for a typed YES
bbox.cmd dialable -Undo      # put .wslconfig back as it was before, restart WSL
```

It is a verb of its own and never part of `bbox run`, because the mode is one line in
`%UserProfile%\.wslconfig` — the user's file, governing every distro on the machine — and it applies
only when WSL restarts, which stops everything running in WSL (this stack, other distros, Docker
Desktop's backend). In mirrored mode the distro's ports ARE the machine's: a Windows program already
listening on 80 or 443 keeps the stack's edge from starting, and the command says so before it asks.
Needs Windows 11 22H2 or later. The machine this was written on was already mirrored; see the header
of `scripts/windows/wsl-mirrored.ps1` for what was and was not measured.

---

# Two ways to think you deployed something when you did not

Both of these bit hard in one session. Neither produced an error at the time; both surfaced much
later as something that looked unrelated.

## 1. `docker cp` is not a deployment

Copying a file into a **running** container changes that container and nothing else. The image is
untouched, so the change lives exactly until the container is recreated — and `bbox run` recreates
containers routinely.

An entire session's UI work was verified live by screenshot, and then silently reverted the next time
the stack came up. The give-away was a comparison harness reporting MORE missing components after the
work than before it: the measurement was right, the deployment had evaporated.

```bash
# fine for a probe — gone on the next recreate
docker cp app.js console-shlomo-laptop:/app/static/app.js && docker restart console-shlomo-laptop

# an actual deployment
./scripts/dc build console && ./scripts/dc up -d --force-recreate console
```

Verify the IMAGE serves it, not the container you patched:

```bash
curl -s "http://$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$v.IPAddress}}{{end}}' console-shlomo-laptop):8000/app.js" | grep -c <something-you-added>
```

## 2. `docker compose -f apps/<app>/docker-compose.yml` forks a second project

Compose derives its project name from the directory. Running a single app's compose file directly
creates a **separate project** whose containers claim the same `container_name` values as the real
stack. Nothing complains until `bbox run` next tries to create one:

```
Conflict. The container name "/mailserver-shlomo-laptop" is already in use by container …
```

A name conflict aborts the whole `up`, not just that service — and Docker can leave containers running
under `<hash>_<name>` because it could not cleanly replace them. Those decorated names then break
anything that looks a container up by name, including healthchecks and capture tooling, which is a
second failure that looks nothing like the first.

Always drive the stack through `bbox`/`scripts/dc` so the project name stays `deployment-hacohen`.
If decorated names appear, they are leftovers — remove them and recreate:

```bash
docker ps -a --format '{{.Names}}' | grep -E '^[0-9a-f]{12}_' | xargs -r docker rm -f
./bbox run
```

Related: a one-shot service must never carry a fixed `container_name` — it exits and lingers, so the
name belongs to a stopped container forever after (see `mailserver-init` in apps/mail).
