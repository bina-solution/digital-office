# CLAUDE.md — start here (agents)

This is **production IaC** for one live VPS. Operating rules are in **[AGENTS.md](AGENTS.md)** — read
it before changing anything (hands-off git, back up before destruction, verify against real output).

## Getting to a healthy running system — `bbox run`

**One command brings the whole stack up on any machine:**

```bash
./bbox run          # → a healthy, routed stack. Then run your task (see below).
```

**On Windows**, that command is `bbox.cmd run`, from CMD/PowerShell, in a plain `git clone` of this
repo anywhere on `C:`. There is no other way to run this stack on Windows — no Docker Desktop, no
separate WSL clone. `bbox.cmd` hands off to WSL, where the project's own Docker engine (not Docker
Desktop, whether or not it's installed) runs exactly the checkout you cloned. See
[running-on-wsl.md](ai/context/running-on-wsl.md).

**On macOS**, the same `./bbox run` works from a plain clone anywhere under your home directory.
There is no Linux kernel on a Mac, so bbox hands itself into the project's own engine: a Lima/vz
Ubuntu guest with **Docker CE 28.5.2 pinned**, created on first run under `~/.bbox/macos` with no
admin and no Docker Desktop — the twin of the WSL hand-off above. The checkout is mounted at the same
path inside the guest. The edge lands on `http://<app>.localhost:8080` (macOS refuses :80 to an
unprivileged process). Engine lifecycle: `./bbox engine start|stop|status|shell|doctor`. See
[packaging/macos.md](packaging/macos.md).

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
| Offline **flow** QA (drives every flow, asserts the effect) | `python3 digital-office/sim/flow-qa.py` — non-zero exit on a failed flow or any JS error |
| …at phone size (drawers, overlays, touch targets) | `python3 digital-office/sim/flow-qa.py --mobile` |
| …one suite only | `python3 digital-office/sim/flow-qa.py drive\|mail\|indox\|console\|scroll\|layout\|windows` |
| **Desktop mode**: every screen in the WINDOW it opens in, and in the smallest one its corner drags to (380×260) — measured and photographed | `python3 digital-office/sim/flow-qa.py windows` → `digital-office/sim/ui-map/windows/<id>[-small].png`; add `--url <console>` to read a running office (→ `…/windows-live/`) |
| **A photograph waits for its screen** — the ONE rule of "drawn" (loaded, no placeholder, no «טוען…», stopped growing), asked from the moment a tile opens: a screen may take 4 s, the camera waits 25 | `scripts/ui-coverage/drawn.py` (`--self-test`), read by the live map, the sim's map and the flow suites. Each prints a screen's time to drawn (the live map: `drawn_ms` in `render-log.json`); a SLOW or NEVER DRAWN screen is a bug to file with its time — never a wait to lengthen |
| **Audit a built sim** (which apps are real vs placeholder) | `node digital-office/sim/verify-sim.mjs [path]` — non-zero exit if any app is a placeholder |
| Inject demo data (drive files / syncs) | `./bbox indox demo run <welcome\|small\|large>` |
| QA onboarding | `./bbox onboarding` |
| Run the INDOX E2E suites | `./bbox indox test` |
| Full health proof (reset→build→up→tests→ui-map→scorecard) | `./bbox baseline` |

`bbox help` lists the full command tree. First bring-up builds images (~10–15 min on a small host);
later runs are cached.

## The three environments — what differs and how `bbox` handles it

Everything below is **autodetected**; each accommodation is a **no-op where it isn't needed**, so the
same `bbox run` is correct on all three. The cloud-sandbox helpers live in [`scripts/lib.sh`](scripts/lib.sh)
(`ccr_*`) and are shared by `bbox run`, `bbox ui-map`, and `bbox baseline` — one implementation, no
duplication.

| Concern | Windows (via `bbox.cmd` → WSL) | Debian VPS (prod) | Claude cloud sandbox |
|---|---|---|---|
| Docker engine | the project's own Docker CE inside WSL's `Ubuntu` distro — **never Docker Desktop**, whether or not it's installed (see [running-on-wsl.md](ai/context/running-on-wsl.md)) | `systemd` service (running) | **none at boot** → `need_docker` starts `dockerd` with `DOCKER_MIN_API_VERSION=1.24` |
| Docker daemon lifecycle | `systemd` inside the distro; `bbox run` provisions it, never hand-started | `systemd` service (running) | started fresh by `need_docker` |
| Docker **major version** | **28.x** (see below) | **28.x** | 28.x |
| Docker API vs Traefik | must be Docker 28.x | must be Docker 28.x | must be Docker 28.x — `baseline` P0 **fails** otherwise |
| Egress TLS | direct (fine) | direct (fine) | **MITM proxy** → `ccr_shadow_bases` re-tags base images with the proxy CA so in-container `pip`/`npm`/`git` verify |
| `ulimit -Hn` | high | high | **low hard cap** → `ccr_clamp_nofile` caps `PG_NOFILE_HARD` so `n8n-postgres` starts |
| Build memory | ample | ample | **small** → `ccr_build_serial` builds first-party images one-at-a-time (avoids concurrent-npm OOM) |
| Writable disk | ample | ample | **~small allowance** → `ccr_build_serial` prunes build cache when free space dips < 6 GiB |
| Container registries | reachable | reachable | **network-policy dependent** → the env must ALLOW image registries (see below); `bbox run` fails fast with a fix hint if they're blocked |
| apt over the proxy | direct | direct | plain-HTTP apt → 403 → shadowed bases switch apt to **https** and builds run `--network host` with proxy build-args |
| Optional browser42 stack | builds/runs if enabled | same | **dropped** — its base is digest-pinned so it can't be CA-shadowed (`BBOX_WITH_BROWSER42=1` to force) |
| `.env` | you provide it | you provide it | auto-generated via `scripts/ci-env.sh` if missing |
| Path handling | none — `bbox.cmd` runs real Linux bash inside WSL, same as the VPS | — | — |

> **Docker 29 does not work, and fails silently.** Traefik v3.3 compiles its docker client against
> API 1.24. Docker 29 raised the daemon's *hard* minimum to 1.40 and capped `DOCKER_MIN_API_VERSION`
> there, so the historical workaround is accepted and does nothing. The result is not an error:
> traefik starts, reports healthy, discovers **zero** routers, and every `*.localhost` host 404s —
> which then looks like a hundred unrelated test failures. Setting `DOCKER_API_VERSION` on the
> traefik container does not help either; 3.3 hardcodes the version rather than reading the
> environment. Run the stack on **Docker 28.x** (what the production VPS runs); `bbox baseline` P0
> now fails fast and says so. Fixing this properly means moving to a traefik release whose docker
> provider negotiates the API version — a change that needs its own validation across every route
> and the authentik forward-auth chain, so it is deliberately not bundled here.

On Windows/VPS none of the cloud helpers fire (no proxy CA, ample limits), so behaviour there is
unchanged. Details + the Docker-29 caveat: [ai/context/healthy-baseline.md](ai/context/healthy-baseline.md).

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
[sim/PORT-PLAN.md](digital-office/sim/PORT-PLAN.md) treats it as **the specification the live UI is
ported toward**. (2) `platform-mockup.html`, the earlier hand-drawn pixel-fidelity mockup, assembled
by `node digital-office/tooling/assemble.js` from the 95 fragments in `tooling/frag/` (verified: a
rebuild reproduces the committed file byte-for-byte, 397 screens) — its comparison harness
`digital-office/verify/*.py` hardcodes `/home/user/deployment-hacohen` and a `reference/real-screenshots/`
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

## Where context lives

| Need | Source |
|---|---|
| Operating rules for agents | [AGENTS.md](AGENTS.md) |
| **Porting the simulation into the live platform** | [digital-office/sim/PORT-PLAN.md](digital-office/sim/PORT-PLAN.md) — ordered phases, acceptance per item, and how to prove parity (`flow-qa.py --url <live>`) |
| Fresh-baseline proof + environment caveats | [ai/context/healthy-baseline.md](ai/context/healthy-baseline.md) |
| Services, domains, ports, networks, run commands | [ai/context/deployment-context.txt](ai/context/deployment-context.txt) |
| **n8n development — the complete model** (code blueprints, bbox verbs, two-writer safety, testing) | [ai/context/n8n-development.md](ai/context/n8n-development.md) |
| n8n operate raw appendix (CLI/API/DB — inspection/emergencies) | [ai/context/n8n-cli.md](ai/context/n8n-cli.md) |
| Writing an app for this platform | [ai/context/build-your-first-app.md](ai/context/build-your-first-app.md) |
| **The office's one palette** («Olive Grove») — the colours, what each hue means, how a screen carries it | [platform-base/bina-ui/theme-tokens.css](platform-base/bina-ui/theme-tokens.css) is the only place a colour is written; gates G27 (every screen's copy is the source) and G82 (no screen, server-drawn page or manifest names a colour of its own) keep it so. How to build to it: "The screen" in [build-your-first-app.md](ai/context/build-your-first-app.md) |
| What a genuinely fresh machine found (7 latent bugs) | [ai/context/fresh-machine-findings.md](ai/context/fresh-machine-findings.md) |
| Running on Windows (the one way — `bbox.cmd`, the project engine, why Docker Desktop is never used) | [ai/context/running-on-wsl.md](ai/context/running-on-wsl.md) |
| **Who owns what** — one owner per fact (state, container-start, app bootstraps, convergence), what was consolidated and what is still open | [ai/context/platform-os-consolidation.md](ai/context/platform-os-consolidation.md) |
| **Target architecture + the plan to release** — layers, the one-owner table, the invariants, and every task left | [ai/context/platform-os-release-plan.md](ai/context/platform-os-release-plan.md) |
| **The core as native binaries** — what "native" means per layer, the one `dgo` binary, the seven steps and their proofs | [ai/context/core-native-plan.md](ai/context/core-native-plan.md) |
| Everything else (architecture, scripts, memory vault) | [README.md](README.md) |
| **View profiles** (mobile / tablet / desktop viewports) | [scripts/ui-coverage/view-profiles.yaml](scripts/ui-coverage/view-profiles.yaml) — one tracked source of truth, read by BOTH the stack ui-map and the offline sim map; `ci_matrix` drives the CI matrix, so adding a profile needs no workflow edit |

`apitools` and `chat` are **in-tree** (baked into this monorepo — no git submodules).
