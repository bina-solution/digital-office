# Running the stack — `bbox run`, the three environments, `digital-office/`

Moved here word for word from the root `CLAUDE.md` on 2026-10-15, when [AGENTS.md](../../AGENTS.md) became
the one entry file every agent loads (DGO-646; why: [azaria-context-architecture.md](azaria-context-architecture.md)).
Read it when a task runs, builds or tests the stack; the operating rules are in AGENTS.md.

**In two pictures** (DGO-357):
- [the OS's layers](diagrams/10-os-layers.svg): what an office declares, the compiler, `.generated/`, and the
  engine that runs it;
- [`bbox run` in every case](diagrams/11-bbox-run.svg): three entries (Windows, macOS, and Linux, a VPS or a
  cloud sandbox), then one path, step by step, as `bbox` runs it.

The sources are Mermaid in [diagrams/src/](diagrams/src/) (`10-os-layers.mmd`, `11-bbox-run.mmd`). A change
to the steps changes the `.mmd`, which is re-rendered with Mermaid 10.9.1 with HTML labels off (each `.svg` says
so in its first line); the SVG is never edited by hand.

## Getting to a healthy running system — `bbox run`

**One command brings the whole stack up on any machine:**

```bash
./bbox run          # → a healthy, routed stack. Then run your task (see below).
```

**On Windows**, that command is `bbox.cmd run`, from CMD/PowerShell, in a plain `git clone` of this
repo anywhere on `C:`. There is no other way to run this stack on Windows — no Docker Desktop, no
separate WSL clone. `bbox.cmd` hands off to WSL, where the project's own Docker engine (not Docker
Desktop, whether or not it's installed) runs exactly the checkout you cloned. See
[running-on-wsl.md](running-on-wsl.md).

**On macOS**, the same `./bbox run` works from a plain clone anywhere under your home directory.
There is no Linux kernel on a Mac, so bbox hands itself into the project's own engine: a Lima/vz
Ubuntu guest with **Docker CE 28.5.2 pinned**, created on first run under `~/.bbox/macos` with no
admin and no Docker Desktop — the twin of the WSL hand-off above. The checkout is mounted at the same
path inside the guest. The edge lands on `http://<app>.localhost:8080` (macOS refuses :80 to an
unprivileged process). Engine lifecycle: `./bbox engine start|stop|status|shell|doctor`. See
[packaging/macos.md](../../packaging/macos.md).

`bbox run` **autodetects the machine and applies whatever it needs** — you do not hand-fix anything.
It sizes the stack to the host's cores (`ensure_perf_profile`), starts Docker if it isn't running,
and adapts to a proxied/low-resource sandbox. So a fresh session on any of the three environments
below reaches the same healthy state from the same command.

Then run whatever the task needs against the running stack, e.g.:

| Task | Command |
|---|---|
| Fresh full UI map | `./bbox ui-map`  → `ci-artifacts/ui-map/ui-map.png` (+ `python3 scripts/ui-coverage/split-map.py` for upload-safe strips) |
| …at another **view profile** | `./bbox ui-map --profile mobile\|tablet\|desktop` → `ci-artifacts/ui-map/<profile>/` |
| Every tile THIS office has, live, with no sign-in | `python3 scripts/ui-coverage/live-ui-map.py --tiles --profile mobile\|tablet\|desktop` → `ci-artifacts/ui-map/<profile>-tiles/NN.png` + `render-log.json` (through the console's own address inside the office network; an app on its own host shows its card, not its UI) |
| Offline UI map (no stack, from the sim) | `python3 digital-office/sim/ui-map.py --all` → `digital-office/sim/ui-map/<profile>/ui-map.png` |
| Offline **flow** QA (drives every flow, asserts the effect) | `./bbox flow-qa` — runs `digital-office/sim/flow-qa.py` in the one image that declares a browser; non-zero exit on a failed flow or any JS error |
| …**against this running office** (`--url`; the suite's own parity proof) | `./bbox flow-qa console --live` → the same assertions aimed at `http://console:8000` |
| …at phone size (drawers, overlays, touch targets) | `./bbox flow-qa --mobile` |
| …one suite only | `./bbox flow-qa drive\|mail\|indox\|console\|scroll\|layout\|windows` |
| **Desktop mode**: every screen in the WINDOW it opens in, and in the smallest one its corner drags to (380×260) — measured and photographed | `./bbox flow-qa windows` → `digital-office/sim/ui-map/windows/<id>[-small].png`; add `--live` to read a running office (→ `…/windows-live/`) |
| **A photograph waits for its screen** — the ONE rule of "drawn" (loaded, no placeholder, no «טוען…», stopped growing), asked from the moment a tile opens: a screen may take 4 s, the camera waits 25 | `scripts/ui-coverage/drawn.py` (`--self-test`), read by the live map, the sim's map and the flow suites. Each prints a screen's time to drawn (the live map: `drawn_ms` in `render-log.json`); a SLOW or NEVER DRAWN screen is a bug to file with its time — never a wait to lengthen |
| **Audit a built sim** (which apps are real vs placeholder) | `node digital-office/sim/verify-sim.mjs [path]` — non-zero exit if any app is a placeholder |
| Inject demo data (drive files / syncs) | `./bbox indox demo run <welcome\|small\|large>` |
| QA onboarding | `./bbox onboarding` |
| Run the INDOX E2E suites | `./bbox indox test` |
| Full health proof (reset→build→up→tests→ui-map→scorecard) | `./bbox baseline` |

`bbox help` lists the full command tree. First bring-up builds images (~10–15 min on a small host);
later runs are cached.

## What a host needs — measured, never guessed

Install from a clone of `https://github.com/bina-solution/digital-office`. What two of our own hosts run on,
each measured on the date given — a number here changes only with a new measurement on a named machine:

| host | measured (2026-11-10) | what it runs |
|---|---|---|
| a Debian 12 VPS | 2 CPUs, 7,952 MiB RAM + 4 GiB swap; the office takes **~44 GB** of disk (images 30.1 GB, volumes 11.5 GB, containers 0.5 GB, checkout 1.7 GB) | its office: 60 containers, public sites and meeting recordings |
| a MacBook, Apple Silicon | 6 cores, 8 GiB RAM, the project's Lima/vz engine | its office |

Measured with `nproc`, `free -m`, `docker ps -q | wc -l`, `docker system df`, `du -sh <checkout>` and
`df -h /` on Linux, and `sysctl hw.ncpu hw.memsize` on the Mac. So the smallest host measured running an office
of 60 containers has **2 CPUs and 8 GB of RAM with swap**. For disk, the ~44 GB above plus room for builds and
recordings — about 60 GB free is a figure DERIVED from it, not one measured. An office with fewer apps switched on
needs less; nothing smaller has been measured yet.

**Windows, once per machine:** WSL2 with an `Ubuntu` distro is what `bbox.cmd` runs in. From an
administrator PowerShell: `wsl --install -d Ubuntu`, restart, and open Ubuntu once to create its user;
`wsl -l -v` must show it with VERSION 2. Then, from the clone: `bbox.cmd install windows` (git and Docker CE
inside the distro, and the mount option traefik's certificates need — it may ask for one `wsl --shutdown` and a
second run), then `bbox.cmd run` (see [running-on-wsl.md](running-on-wsl.md)).

## The three environments — what differs and how `bbox` handles it

Everything below is **autodetected**; each accommodation is a **no-op where it isn't needed**, so the
same `bbox run` is correct on all three. The cloud-sandbox helpers live in [`scripts/lib.sh`](../../scripts/lib.sh)
(`ccr_*`) and are shared by `bbox run`, `bbox ui-map`, and `bbox baseline` — one implementation, no
duplication.

| Concern | Windows (via `bbox.cmd` → WSL) | Debian VPS (prod) | Claude cloud sandbox |
|---|---|---|---|
| Docker engine | the project's own Docker CE inside WSL's `Ubuntu` distro — **never Docker Desktop**, whether or not it's installed (see [running-on-wsl.md](running-on-wsl.md)) | `systemd` service (running) | **none at boot** → `need_docker` starts `dockerd` with `DOCKER_MIN_API_VERSION=1.24` |
| Docker daemon lifecycle | `systemd` inside the distro; `bbox run` provisions it, never hand-started | `systemd` service (running) | started fresh by `need_docker` |
| Docker **major version** | **28.x** (the installer pins it; see below) | **28.x** | 28.x |
| Docker API vs Traefik | the daemon must answer a v1.24 client — `baseline` P0 asks it | the same | the same |
| Egress TLS | direct (fine) | direct (fine) | **MITM proxy** → `ccr_shadow_bases` re-tags base images with the proxy CA so in-container `pip`/`npm`/`git` verify |
| `ulimit -Hn` | high | high | **low hard cap** → `ccr_clamp_nofile` caps `PG_NOFILE_HARD` so `n8n-postgres` starts |
| Build memory | ample | ample | **small** → `ccr_build_serial` builds first-party images one-at-a-time (avoids concurrent-npm OOM) |
| Writable disk | ample | ample | **~small allowance** → `ccr_build_serial` prunes build cache when free space dips < 6 GiB |
| Container registries | reachable | reachable | **network-policy dependent** → the env must ALLOW image registries (see below); `bbox run` fails fast with a fix hint if they're blocked |
| apt over the proxy | direct | direct | plain-HTTP apt → 403 → shadowed bases switch apt to **https** and builds run `--network host` with proxy build-args |
| Optional browser42 stack | builds/runs if enabled | same | **dropped** — its base is digest-pinned so it can't be CA-shadowed (`BBOX_WITH_BROWSER42=1` to force) |
| `.env` | you provide it | you provide it | auto-generated via `scripts/ci-env.sh` if missing |
| Path handling | none — `bbox.cmd` runs real Linux bash inside WSL, same as the VPS | — | — |

> **Docker and traefik: ask the daemon, not its version number.** Traefik v3.3 compiles its docker
> client against API 1.24, so what matters is whether the daemon answers a v1.24 client. If it does
> not, the failure is SILENT: traefik starts, reports healthy, discovers **zero** routers, and every
> `*.localhost` host 404s — which then looks like a hundred unrelated test failures. An earlier version
> of this note said Docker 29 refuses that client whatever is set; it did not hold when measured.
> **`DOCKER_MIN_API_VERSION=1.24`** lowers a daemon's floor to it: bbox's systemd drop-in for the project
> engine sets it (`bbox`, ensure_project_engine), and the cloud sandbox's `need_docker` starts dockerd
> with it. On record: Docker **29.3.1** started with it passed the baseline (`.ci-cd/baseline-summary.md`),
> and Docker **29.1.3** on the Dell, 2026-08-21, routed end to end (auth.localhost 302,
> glitchtip.localhost 200, an unknown host 404 — issues/docker29-traefik-warning-does-not-reproduce.yaml)
> with the variable unrecorded: bbox could not install its drop-in on that run, and the 404s seen there
> had another cause, a socket mount that had become a directory. `bbox baseline` P0 asks the one question
> traefik asks — can a v1.24 client list containers on this endpoint (`scripts/baseline.sh`) — and marks
> P0 red when the answer is no or the daemon cannot be reached; the run goes on and ends RED. The
> installer (`debian-install.sh`) and dgo's engine check still pin **Docker 28.x** by version, and the
> offices run 28.x — all but the Dell, which runs 29.

> **Never run `docker buildx history …` (ls, inspect, logs…) on an office's engine.** On a daemon whose BuildKit is
> older than v0.29.0, Docker 28.5.2 among them, a build-history list with a limit (`ls` sends 50) panics dockerd
> when a build-cache prune has soft-deleted a record that a running build still holds (moby/buildkit#6614).
> `bbox run` prunes, then builds. On the HP at 04:29:18 UTC on 2026-11-13, an agent watching a follow take's build
> ran it, and dockerd died. The restarted daemon killed all 72 containers and restarted none of them, so the office
> was down for six hours (DGO-1863).
> To watch a build, read its log: the take's `data/follow/run-*.log`, or `docker top` of the process building.
> DGO-1871 (the engine) and DGO-1872 (a guard) lift this rule.

On Windows/VPS none of the cloud helpers fire (no proxy CA, ample limits), so behaviour there is
unchanged. Details: [ai/context/healthy-baseline.md](healthy-baseline.md).

> **A kernel that STACKS the container's AppArmor label stops every postgres (Ubuntu 26.04, kernel
> 7.0.0-42 and later).** Ubuntu's default `kernel.apparmor_restrict_unprivileged_unconfined=1` makes
> the kernel turn runc's profile change into a *stack*, so a container's processes are labelled
> `docker-default//&unconfined` rather than `docker-default`. Docker's profile allows `signal` and
> `ptrace` only to the literal peer `docker-default`, so **a container's processes can no longer
> signal each other** — and the failure looks like anything but that. Measured on the Dell
> 2026-11-09, with `postgres:17` started directly as `postgres` so that gosu is not involved at all:
> autovacuum is cancelled every naptime (`autovacuum worker took too long to start`),
> `pg_reload_conf()` and `pg_cancel_backend()` answer `Permission denied`, `docker stop` kills the
> container because `tini` cannot forward SIGTERM, and the next start runs crash recovery that stalls
> on `the database system is starting up`. The production symptom is the one you see first: gosu
> spins at ~80% CPU forever and the container never logs a line
> (work item **DGO-1604** carries the whole measurement and the Dell's evidence; upstream
> [moby/moby#54099](https://github.com/moby/moby/issues/54099),
> [containerd/containerd#14485](https://github.com/containerd/containerd/issues/14485) and
> [Launchpad #2172422](https://bugs.launchpad.net/ubuntu/+source/linux/+bug/2172422) are all open,
> with no fix released.)
>
> - **Read it:** `./bbox apparmor status` — two facts from one throwaway container (the label, and
>   whether `kill -TERM` to a sibling gets through). `./bbox baseline` P0 fails on a host with the
>   condition and names this fix; `./bbox run` prints it before it brings anything up.
> - **Fix it:** `sudo ./bbox apparmor install` — copies
>   `packaging/linux/apparmor/docker-default.dgo` to `/etc/apparmor.d/docker-default` and loads it
>   from there. The file is Docker's own profile plus the SAME profile's stacked form for `signal`
>   and `ptrace` (containerd#14487's proposal), and one widening: on a session bus a container may say
>   Hello and ask `org.gnome.Mutter.IdleMonitor.GetIdletime`, so the office's `machine` can tell
>   whether somebody is at the desk (DGO-1797; what that exposes is in the profile's header). Two
>   consequences worth knowing:
>   the copy in `/etc/apparmor.d` is what makes the fix **survive a reboot** (a load alone evaporates
>   at the next boot, silently), and **containers that are already running keep the rules they
>   started with** — recreate them (`bbox run`) or the hung ones stay hung. `./bbox apparmor
>   validate` parses the profile without loading anything, `./bbox apparmor verify` says whether the
>   signal now gets through. It is upstream's tested shape, not a mechanism this office has proven on
>   a live host yet: the proof is `verify` on a host where it ran.
> - **Loading a profile is a host policy change and the owner's act** — `bbox run` and `bbox baseline`
>   never do it. What is NOT acceptable, on any host: `sysctl
>   kernel.apparmor_restrict_unprivileged_unconfined=0` and `apparmor=unconfined` on a container. Both
>   trade the host's hardening for one app's convenience; either is a decision about a specific host,
>   never a product default.
> - **Not fixable from the image side.** "Start postgres as its own user" removes the gosu hang and
>   leaves a database that cannot vacuum, reload, cancel or shut down cleanly — measured, above. Both
>   postgres images the office runs (`postgres:17`, `supabase/postgres`) also fail INSIDE their own
>   entrypoint, on the same denial (`pg_ctl: could not send stop signal … Permission denied`), and
>   that entrypoint needs root for its own chmod/init work — so no compose-level `user:` change can
>   even reach the second half of the problem.
> - **Re-render the profile when the engine changes.** It is rendered from moby/profiles' template,
>   which moby, containerd and libpod keep in sync; a newer engine may deny a socket family this copy
>   does not. Never widen a rule to make something work.


> **A kernel that STACKS the container's AppArmor label stops every postgres (Ubuntu 26.04, kernel
> 7.0.0-42 and later).** Ubuntu's default `kernel.apparmor_restrict_unprivileged_unconfined=1` makes
> the kernel turn runc's profile change into a *stack*, so a container's processes are labelled
> `docker-default//&unconfined` rather than `docker-default`. Docker's profile allows `signal` and
> `ptrace` only to the literal peer `docker-default`, so **a container's processes can no longer
> signal each other** — and the failure looks like anything but that. Measured on the Dell
> 2026-11-09, with `postgres:17` started directly as `postgres` so that gosu is not involved at all:
> autovacuum is cancelled every naptime (`autovacuum worker took too long to start`),
> `pg_reload_conf()` and `pg_cancel_backend()` answer `Permission denied`, `docker stop` kills the
> container because `tini` cannot forward SIGTERM, and the next start runs crash recovery that stalls
> on `the database system is starting up`. The production symptom is the one you see first: gosu
> spins at ~80% CPU forever and the container never logs a line
> (work item **DGO-1604** carries the whole measurement and the Dell's evidence; upstream
> [moby/moby#54099](https://github.com/moby/moby/issues/54099),
> [containerd/containerd#14485](https://github.com/containerd/containerd/issues/14485) and
> [Launchpad #2172422](https://bugs.launchpad.net/ubuntu/+source/linux/+bug/2172422) are all open,
> with no fix released.)
>
> - **Read it:** `./bbox apparmor status` — two facts from one throwaway container (the label, and
>   whether `kill -TERM` to a sibling gets through). `./bbox baseline` P0 fails on a host with the
>   condition and names this fix; `./bbox run` prints it before it brings anything up.
> - **Fix it:** `sudo ./bbox apparmor install` — copies
>   `packaging/linux/apparmor/docker-default.dgo` to `/etc/apparmor.d/docker-default` and loads it
>   from there. The file is Docker's own profile plus the SAME profile's stacked form for `signal`
>   and `ptrace`, and nothing wider (containerd#14487's proposal). Two consequences worth knowing:
>   the copy in `/etc/apparmor.d` is what makes the fix **survive a reboot** (a load alone evaporates
>   at the next boot, silently), and **containers that are already running keep the rules they
>   started with** — recreate them (`bbox run`) or the hung ones stay hung. `./bbox apparmor
>   validate` parses the profile without loading anything, `./bbox apparmor verify` says whether the
>   signal now gets through. It is upstream's tested shape, not a mechanism this office has proven on
>   a live host yet: the proof is `verify` on a host where it ran.
> - **Loading a profile is a host policy change and the owner's act** — `bbox run` and `bbox baseline`
>   never do it. What is NOT acceptable, on any host: `sysctl
>   kernel.apparmor_restrict_unprivileged_unconfined=0` and `apparmor=unconfined` on a container. Both
>   trade the host's hardening for one app's convenience; either is a decision about a specific host,
>   never a product default.
> - **Not fixable from the image side.** "Start postgres as its own user" removes the gosu hang and
>   leaves a database that cannot vacuum, reload, cancel or shut down cleanly — measured, above. Both
>   postgres images the office runs (`postgres:17`, `supabase/postgres`) also fail INSIDE their own
>   entrypoint, on the same denial (`pg_ctl: could not send stop signal … Permission denied`), and
>   that entrypoint needs root for its own chmod/init work — so no compose-level `user:` change can
>   even reach the second half of the problem.
> - **Re-render the profile when the engine changes.** It is rendered from moby/profiles' template,
>   which moby, containerd and libpod keep in sync; a newer engine may deny a socket family this copy
>   does not. Never widen a rule to make something work.


> **Cloud network policy (important):** a Claude-Code-on-the-web environment's egress is set by the
> **network policy chosen when the environment is created**. `bbox run` builds images from source, so
> the policy **must allow container image registries / layer CDNs** (Docker Hub `registry-1.docker.io`
> + its Cloudflare CDN, and GHCR `ghcr.io` + `pkg-containers.githubusercontent.com`). If they're
> blocked, no images can be pulled and `bbox run` stops with a clear hint — **recreate the environment
> with a registry-allowing policy** ([docs](https://code.claude.com/docs/en/claude-code-on-the-web)).
> bbox cannot work around a blocked registry.

## What `digital-office/` is (and is not)

`digital-office/` (322 tracked files, the repo's second-largest tree) is the **design/spec workbench
for the platform's UI — dev-only, never shipped, never run by CI.** It produces two offline
single-file artifacts and nothing else. (1) `platform-sim.html`, built by `node
digital-office/sim/build.mjs`, embeds the **real** frontends — `platform-base/{console,
any-concurrency,notifications,machine,connections,app-management}` and `apps/{my-docs,drive,mail/mailview,apitools/feature-validation}`
— plus one sim-owned fork (`sim/apps/indox`) and `sim/wadmin.html`, each
behind a per-app `fetch`/XHR mock, so the whole platform runs in a browser with no stack; it is the
input to `sim/flow-qa.py`, `sim/ui-map.py`, `sim/verify-sim.mjs` and `verify/sim_qa.py`, and
[sim/PORT-PLAN.md](../../digital-office/sim/PORT-PLAN.md) treats it as **the specification the live UI is
ported toward**. (2) `platform-mockup.html`, the earlier hand-drawn pixel-fidelity mockup, assembled
by `node digital-office/tooling/assemble.js` from the 95 fragments in `tooling/frag/` (verified: a
rebuild reproduces the committed file byte-for-byte, 397 screens) — its comparison harness
`digital-office/verify/*.py` hardcodes `/home/user/digital-office` and a `reference/real-screenshots/`
directory that does not exist here, so that half is unrunnable as committed. **What depends on it:**
`scripts/ui-coverage/live-ui-map.py` and `scripts/ui-coverage/sim-live-parity.py` hard-require
`sim/ui-map.py` (parse / import) and would break if it vanished; `scripts/ui-coverage/pixel-diff.py`
reads it only for panel captions and degrades gracefully; `apps/chat/bots/intent.js` and
`apps/chat/chatapi/adapters/local.js` cite `sim/mocks/wadmin.js` in comments as the behavioural
contract; and the sim map shares its viewport definitions with the live map via
`scripts/ui-coverage/view-profiles.yaml`. **What it is NOT:** not a layer-3 app (no `app.json`, no
entry in `platform.state.yaml`, no compose service, and `bbox` dispatches only under `apps/` and
`platform-base/`, so it has no verbs); not shipped (`packaging/stage-control.py` stages an
allowlist that never names it, no Dockerfile COPYs it, no compose file mounts it); not CI-covered
(no workflow runs anything under it, G32 `engine-bypass-lint` and `charset-first-lint` explicitly
skip it, and only G12 `compile-lint` touches it — as a syntax check of its 11 `.py` files); and
**not dead** — the platform-OS refactor repointed `build.mjs` off `production/`/`development/` onto
`apps/`/`platform-base/`, and every path it names resolves today. `./bbox ui-map` is the *live*
map and does not read this tree at all.
