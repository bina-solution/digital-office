# The core as native binaries — what it means here, and the order (core-005, DGO-481)

The owner, 2026-10-08: *"I want DGO core to be replaced entirely with Go apps … everything we have in
the core layer should be very efficient, very fast, very Go — like minimum Go, C … that can compile
into any operating system without needing virtualization or without needing containers … DGO core
has the app management, and there we start getting the docker engine … layer two and layer three can
install container apps."*

Read as architecture, that is one sentence: **everything that must exist BEFORE a container can
exist is a native binary; everything that is an app stays a container.** This note says what that
is in this repository, measured, and the order in which it is built so that every step ships alone.

## 1. What is native today (built, tested, on `hp-dgo`)

| binary | item | state | size |
|---|---|---|---|
| `packaging/installer/` — the download: verifies a signed manifest, fetches the core, hands over | core-007 | Go, stdlib-only, 11 tests, cross-compiles 6 OS/arch; needs a signing key + a manifest host (owner infra) | 5.3 MB |
| `platform-base/forward-auth/` — the identity service that replaces authentik | core-006 | Go, stdlib-only, 28 tests; HELD before cutover on F1–F3 (needs-azaria.md §2) | 7.8 MB |

Both are proof that the owner's constraint holds for this codebase: `CGO_ENABLED=0`, no module
beyond the standard library, one `go build` per target from one host.

## 2. What the core IS, by layer, after the move of n8n (core-001)

Measured on `hp-dgo` at `6eb0c9f0`: layer 1 = app-management, traefik, postgres, redis, authentik,
connections, autoheal; layer 2 = console, notifications, machine, data-management, bina-ui (a
library). Everything else is `apps/` (layer 3), n8n and any-concurrency included.

| | today | native target | why it moves — or stays |
|---|---|---|---|
| **`bbox`** (the CLI: run, apps, status, every app's verbs) | 1,000 lines of bash + `scripts/lib.sh` | **`dgo` — the one binary a person downloads and runs** | it is what must exist before Docker does: it provisions the engine (WSL/Lima/systemd — today `bbox.cmd`, `bbox engine`), serves the first-run wizard, and dispatches app verbs. The installer (core-007) hands over to it |
| **the compiler** `platform/manager/reconcile.py` (+ `serve.py`, `catalog.py`) | 3,200 lines of Python, needs python3 + PyYAML on the host | **inside `dgo`** (`dgo render`, `dgo validate`, `dgo office-set` …) | the compiler is layer 0: it decides which containers exist. Keeping it in Python means the host needs Python before the core can start; the Mac and Windows hand-offs exist mostly to get a Linux python3 |
| **app-management** (the control plane: lifecycle, the apps screen's API, the install catalog) | a Python/Flask container that mounts the repo and the engine socket | **inside `dgo`** (a `dgo serve` process on the host, or a scratch container of the same binary) | it is the second thing that must exist before a container can: the wizard talks to it. Its one hard dependency is the engine socket, which the host owns |
| **connections** (the credential plane) | a Python container with a vault volume | **inside `dgo`** (the vault stays a file the binary owns, mode 600) | the secrets every container is given must exist before the containers do |
| **forward-auth** (identity) | a Python-heavy authentik estate (1.1 GB, 4 containers) | **the Go service, already written** | core-006; a container of a scratch image or a host process, the same binary |
| **console** (the shell, the first-run wizard) | a Flask container serving static files + proxies | **static files served by `dgo`**, the proxies as `dgo` routes | the shell's server is 850 lines that proxy and serve; nothing in it needs Python |
| **traefik, postgres, redis** | containers | **stay containers** | they are somebody else's binaries, already native, already pinned; the engine exists by the time they are needed |
| **notifications, machine, data-management, autoheal** | Python containers | **stay containers for now** (layer 2, "after the engine") | each is an app with a screen; none has to exist before a container can. Candidates for Go later, each on its own merit |
| **every layer-3 app** | containers | **containers** | the owner's line: "layer two and layer three can install container apps" |

So "native" is ONE binary, `dgo`, that absorbs four things that are today bash + three Python
services: the CLI, the compiler, the control plane and the credential plane — plus the two binaries
that exist. The console's static files ride inside it (`embed`).

## 3. The order — each step ships alone, with its own proof and its own rollback

| # | step | proof | rollback |
|---|---|---|---|
| 0 | **Freeze the contract.** The compiler's verbs (`validate`, `render`, `compose-files`, `services`, `set-state`, `office-get/set`, `remote-get/set`, `capability-provider` …) and app-management's routes are the interface every app and gate already uses. Write them down as the `dgo` surface, test by test (the 173 existing tests are the spec). | a table in this note, every verb with its caller | none — nothing built |
| 1 | **`dgo` = the CLI.** A Go binary that does what `bbox` does by delegating: engine provisioning (`bbox.cmd`/`engine` logic), `run`, `status`, app verb dispatch (`<root>/<id>/hooks/<verb>`), and that *exec*s the Python compiler for the verbs it has not absorbed yet. `bbox` becomes a one-line shim to it. | `./dgo run` brings the office up on all three environments; every `bbox` acceptance (`bbox dgo test N`, `baseline`) passes through the shim | the shim is deleted; `bbox` is untouched underneath |
| 2 | **The compiler in Go.** Port `reconcile.py` verb by verb behind the same CLI, each verb diff-tested against the Python output on the committed catalog (`render` must produce byte-identical `.generated/`). Python stays as the oracle until the last verb matches. | a `go test` that renders the repo's catalog with both and diffs; the 60 gates run unchanged (they call the verbs) | `DGO_COMPILER=python` flips back per verb |
| 3 | **The control plane in Go.** app-management's routes (`/api/apps`, lifecycle, `/api/office`, the link guards G85 enumerates) as `dgo serve`; the apps screen's static files served by it. The existing 78 tests become the Go suite's cases. | the apps screen and the wizard work against `dgo serve`; G85 green; a linked office's 403s unchanged | app-management's container is still built; `BBOX_CONTROL_PLANE=container` |
| 4 | **The console's server in `dgo`.** The shell's proxies (`/a/<alias>/`, the door for linked offices, `/api/me|modules|version|office`) and its static files `embed`ded. | `console.localhost` served by `dgo`; the ui-map and the sim's flow suites pass against it | the console container stays buildable |
| 5 | **The credential plane in `dgo`.** The vault as a file the binary owns; providers compiled from manifests as today; the wizard's connect flows. | the connections screen works; G8 and the connection gates green | the container stays buildable |
| 6 | **forward-auth cutover** (core-006's window, after F1–F3) and authentik retired. | the window's own sweep (design note §6.6) | one file |
| 7 | **The installer points at `dgo`** (core-007): the signed manifest names the `dgo` binary per OS; "download → hello → terms → the core downloads → the wizard" is the whole first run, with no git clone. | a fresh machine on each OS reaches the wizard from the download alone | the manifest's previous release |

Steps 1–5 are additive: the Python services keep running until the Go one is proven against them,
and every step is a flag away from the old path. Nothing is removed before its replacement has run
the office for a day.

**The release lane (landed 2026-10-10, beside the steps):** `packaging/build-binaries.sh` builds the
three binaries that exist — `dgo-install`, `dgo`, `forward-auth` — for windows/darwin/linux × amd64/arm64
with one command: vet + tests, `CGO_ENABLED=0 -trimpath -buildvcs=false`, a double build that proves the
bytes reproducible, `SHA256SUMS`, and the website's download tree (`dl/<os>/<arch>/{dgo-core, manifest.json}`)
signed by `packaging/relsign` (stdlib `crypto/ed25519`, the installer's own `signedMessage()` bytes — the
installer's test signs with relsign and verifies with the stub). `.github/workflows/release-binaries.yml`
runs it on a `v*` tag and attaches the binaries to the GitHub release; without the `DGO_RELEASE_KEY`
secret the manifests are unsigned drafts the stub refuses. Measured on the HP: 18 binaries, 2–7 MB each,
reproducible, 4½ minutes cold. What stays the owner's: the key, and serving `dl/` from the site (web).
Each later step (2–5) ships through this same lane — a step is "released" when its binary is in the tag.

**Step 2, first slice (2026-10-10): the YAML reader — `packaging/dgo/internal/yamlish`.** Every compiler
verb reads `platform.state.yaml` or a compose file before it can answer, and stdlib Go has no YAML; a
library would answer YAML 1.2 where the compiler lives on PyYAML's 1.1 (`on` is true, `0755` is 493,
`1e5` is a string). So the reader is the measured subset the office's 63 files use — block and flow
mappings and sequences, plain, quoted (also multi-line) and block scalars, comments — with PyYAML's
resolver regexes verbatim, insertion-ordered maps, and a loud error for anchors, aliases, merge keys,
tags, multi-documents, complex keys and unquoted timestamps. The proof is `TestCorpusMatchesPyYAML`:
PyYAML runs beside it on every file the compiler reads and the two canonical-JSON renderings must be
byte-identical (56/56 on the HP; the test skips where no Python with PyYAML is on PATH).

**Step 2, second slice (2026-10-10): `enabled-apps` is native — `packaging/dgo/internal/compiler`.**
The catalog (`load_catalog`: both roots, sorted, the FATAL refusals verbatim), the state file
(`load_state` with `ensure_state`'s three answers, `disposition`'s two shapes and Python truth, the
legacy id rename) and the resolver (`resolve`: hard strengths, provider pull-in, ops negotiation, the
binding → default_provider → only-candidate selection, conflicts, `after`/weak edges, the DFS with
cycle naming) are ported line for line; `dgo enabled-apps` answers in-process and `DGO_COMPILER=python`
delegates it again. Proof: `TestEnabledAppsMatchesPython` runs reconcile.py on this checkout beside it
— same 23 lines, same exit code, same error set — plus one fixture per resolver rule (12 tests). On the
HP the native answer takes 0.13 s against Python's 0.63 s.

**Step 2, third slice (2026-10-10): `validate` is native, and `enabled-apps` validates first — the one
divergence closed.** `validate(cat)` ported check for check (required and unknown fields, declared types
and enums at every depth with Python's quirks kept — a bool is an int, an explicit null fails both
walks — a sub-object's required keys, kind, strengths, route and tile conflicts, the agent's brief, the
compose file); `dgo validate` prints the same OK line as reconcile.py (byte-identical on this
checkout, 0.12 s), and the resolver verbs refuse an invalid manifest with the same FAILED list before
they resolve, exactly as main() does. 22 compiler tests (two oracles, one fixture per rule). What the
schema declares that neither validator enforces — `pattern`, `minimum`, `minItems`, `oneOf`,
`additionalProperties` below the top level — stays unenforced on both sides, by design: the contract is
reconcile.py's behaviour, not the schema's vocabulary. Next: `compose-files` (needs `.generated`, the
bootstrap-inputs overlay and the effective CPU budget — render-adjacent), then the emitter.

## 4. What this does NOT do

* It does not make layer-3 apps native. They are containers by design, on every OS.
* It does not replace traefik, postgres or redis — they are already native, and not ours.
* It does not change the manifests, the state file, the hooks or the gates: the contract is kept, the
  implementation moves. A gate that calls `python3 platform/manager/reconcile.py validate` calls
  `dgo validate` the day the shim lands, and nothing else about it changes.

## 6. Step 0, done: the compiler's contract, measured (2026-10-09, `git grep` over the tracked tree)

Every call of `platform/manager/reconcile.py <verb>` outside the compiler itself, history and
documents excluded — the verbs `dgo` must answer, and who will notice if one is missing:

| verb | call sites | who calls it |
|---|---|---|
| `render` | 24 | `bbox` (4), `scripts/lib.sh` (3), app-management (2), CI (`ci-verify.yml`, `release-bundle.yml`), the glitchtip app's hooks + blueprint, `quiet-mode.sh`, `qa-fix-loop.sh`, `fresh-machine-check.sh`, dgo-extend's `project` hook, n8n's `push-app`, ui-coverage's inventory, two gates (`auth-lint`, `fresh-clone-lint`) |
| `set-state` | 19 | dgo-extend (`migrate` hook, `converge.py`, `move.py`, a test), `quiet-mode.sh`, `state-writer-lint`, app-management, `bbox`, `qa-fix-loop.sh` — and **Azaria's agent config** (`agent-presets/azaria/agent.cordis.yml`) |
| `blueprints` | 11 | every n8n hook (`pull`, `pull-app`, `push`, `push-app`, `present`, `status`, `unpush`), `ci-verify.sh`, `app-tag-lint` |
| `validate` | 9 | CI (2), `manifest-lint`, `capability-use-lint`, `bbox`, `fresh-machine-check.sh`, a dgo-extend test |
| `enabled-apps` | 9 | `scripts/lib.sh`, `deployment-archive.py`, ui-coverage's inventory, two gates, dgo-extend tests |
| `plan` | 6 | `bbox`, dgo-extend's `move.py` + tests, `profile-gate-lint` |
| `compose-files` | 3 | `scripts/lib.sh` (the one place that answers "which -f files are the stack"), `compose-invocation-lint` |
| `compose-services` | 3 | dgo-extend's `converge.py` + a test, `deployment-archive.py` |
| `capability-provider` | 3 | `bbox` (2), app-management (the workflow provider's hooks) |
| `required-by` | 3 | the compiler's own tests |
| `remote-get` / `remote-set` | 3 | dgo-extend's `project` hook and `converge.py`; a compiler test |
| `office-get` / `office-set` | 2 | app-management (`/api/office`, the install wizard's record) |
| `serve-plan` | 2 | dgo-extend tests |
| `apply`, `generations`, `rollback`, `up`, `services`, `shells` | 1 each | `bbox`, `quiet-mode.sh`, `scripts/ci/derive-services.sh` |

Three things the table says that a plan written from memory would not: (1) the gates are callers
too — ten of them shell out to the compiler, so step 2 cannot flip a verb without the gate suite
agreeing; (2) **three callers are not code**: a plan text (`apps/project-pln/plans/office.yaml`), an
app's blueprint (`platform-base/glitchtip/blueprint.yml`) and the office agent's own configuration —
each names the command a person or an agent types, and each changes with the shim; (3) `set-state`
has more call sites than any verb but `render`, from six different surfaces — the one writer of the
state file is already the compiler, which is what makes step 2 possible at all.

The app-management routes (20, enumerated by G85 with their write sinks) and `bbox`'s own verbs
(`bbox help` is generated from `apps/*/hooks` and `platform-base/*/hooks`, so the list is the tree's)
are the other two halves of the contract; both are already measured by a gate, which is the
condition for step 3.

## 5. The sizes, for the owner's "tiny"

Today a first run needs: a git clone (3,600 files), python3 + PyYAML on the host, docker, and a 10–15
minute image build. After step 7: one download (the installer, ~5 MB) that fetches one binary
(`dgo`, measured target 10–15 MB with the console's files embedded), which provisions the engine and
pulls the images CI published (DGO-41). The clone exists only for developers.
