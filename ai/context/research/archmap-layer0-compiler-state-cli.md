# DGO layer 0 — decision map: compiler, state model, CLI

Read-only map of `hp-dgo` @ `7347f738` (2026-10-14). Line anchors into `platform/manager/reconcile.py` are the **committed** file (`git show HEAD:…`, 3,219 lines); the working tree carries another writer's +304 uncommitted lines, so live numbers drift from ~line 494 on.

## 1. The pipeline — manifests + state → resolve → render → .generated → compose

| # | Stage | Where | What it decides |
|---|---|---|---|
| 1 | **Load catalog** | `reconcile.py:495-520 load_catalog` | globs `platform-base/*/app.json` (layers 1-2) and `apps/*/app.json` (layer 3). FATAL on id≠dirname, layer≠root, duplicate id. 43 manifests today (14 base + 30 apps − 1 non-app dir). |
| 2 | **Ensure + load state** | `:526-582 ensure_state / load_state` | `platform.state.yaml` is created only if missing: restore from `ORIG_HEAD` → else tracked `platform.state.default.yaml` → **refused** if `.generated/` exists (a silent reset). `schema_version==1` enforced; `offices→dgo-extend` id rename normalised on read. |
| 3 | **Validate** | `:662-756 validate`, `:586 _check_enums`, `:627 _check_types` | Structural check against `platform/schema/app.schema.json` *without* a jsonschema library; enums recursively; route-host and console-tile uniqueness; `agent.context` must exist, be inside the app, ≤6,000 bytes; `compose` must exist and is forbidden for `kind: blueprint\|library`. |
| 4 | **Resolve** | `:760-910 resolve` | `enabled_ids` (:268) seeds the closure; hard strengths (`requires/requisite/binds_to`, :55) pull providers in transitively with **ops negotiation**; provider selection = state `bindings` → consumer `default_provider` → only candidate → *error naming all candidates*; `conflicts` reported naming both apps; ordering edges only from `after` and never across `dependency: weak`; DFS names any cycle. |
| 5 | **Plan** (optional) | `:1792 inputs_digest`, `:1804 write_plan`, `:2616-2635 apply` | `.generated/plans/NNNN.yaml` carries start order, bindings, services, `pulled_in`; `apply` refuses a plan whose inputs digest or start order moved. |
| 6 | **Render** | `:1879-1950 render` | `sync_identity()` rewrites `.env`'s `#@derived slug` lines → `archive_generation()` → `compose.yml` include list → `routing.override.yml` (traefik labels + `contributes.env`, :1642) → `connections.override.yml` (broker cutovers, :1587) → glitchtip projects → `serve.plan` (remote plane, `serve.py`) → `registry/` for console + connections (:2830) → `registry/` agent briefs (:2685) → authentik blueprint `zz-generated-apps.yaml` (:3033) → `resolved.json`. |
| 7 | **Compose file list** | `:948-976 compose_files` | Canonical `-f` order: `compose.yml`, routing, remote, connections (**last of the overlays — it blanks env**), `authentik-bootstrap.override.yml` (digest label, :1005), `cpu-budget.effective.yml` (:1065, overlay filtered to services that still exist). |
| 8 | **Write discipline** | `:913-945 write` | LF on every platform; a byte-identical file is **not rewritten** (watchers — the sign-in worker re-applied 40 providers twice per render). |
| 9 | **Shell bring-up** | `bbox:512-677 run` | `need_docker` (:124, provisions `/run/bbox-docker.sock`) → `ensure_rendered` (:192) → `ensure_network` → `ensure_perf_profile` (:221) → refuse foreign containers → `run_app_hooks prepare` → cloud `ccr_*` → `dc up -d --build --wait` → `ensure_sso_current` (:270) → `ensure_converged` (:302, `POST /api/reconcile` on whichever app provides `control-plane`) → `run_app_hooks onboard` → G70 lint. |
| 10 | **Compose invocation** | `scripts/lib.sh:413 dcx`, `:328 compose_args`, `scripts/dc` | renders if `.generated/compose.yml` is missing, then shells `reconcile.py compose-files`; `BBOX_COMPOSE` is a fixed plugin path; `--project-directory .`; after `up`: `netns_rejoin`, `cpu_caps_apply`. `scripts/dc` refuses an empty `.env` or one without `DEPLOYMENT_NAME`. |

Verb surface (`reconcile.py:2264-2290 main`): 20 verbs — `plan render up validate compose-files services required-by compose-services blueprints generations rollback apply enabled-apps set-state capability-provider serve-plan remote-get/set office-get/set`. `compose-files` deliberately neither validates nor resolves ("must stay usable while a manifest is broken").

## 2. Design decisions stated beside the code

| Decision | Where | Stated reason | Alternative rejected |
|---|---|---|---|
| **The directory is the layer** | `reconcile.py:35-44`; AGENTS.md Layout; G9/G31 | "what can I uninstall?" is `ls apps/`, not reading 25 manifests | a `layer` field alone |
| Compiler is a pure function (catalog, state) → `.generated/` | `:1-11` docstring | strangler migration stayed byte-identical per step; legacy lane now empty (`platform/legacy-capabilities.yaml`) | hand-maintained compose |
| Three dispositions `enabled/disabled/archived` with provenance `by:` | `:217-228` | bool "could not express the states a real app engine needs"; archived = images gone, **data and tile kept** (Android 15) | `enabled: bool` |
| One text-surgery writer per state block | `:274-300 set_disposition`; `:370 set_office`; `:441 set_remote` | file is ~80 % comments; a YAML round-trip deletes them; four regex writers in two shapes had drifted | YAML load/dump; per-caller regex |
| Provider selection is explicit and auditable | `:815-845` | `ok[:1]` was "silent, non-deterministic, unauditable"; package-manager order (binding → default_provider → only one) | first match |
| Conflicts fail the plan naming both | `:848-862` | Debian Breaks/Conflicts; Gateway API forbids silent drop | drop one side |
| Ordering only via `after`, never through weak links | `:865-870` | Fuchsia/systemd: requirement ≠ ordering | ordering from strength |
| Plan as approvable artifact with inputs digest | `:1778-1788` | OLM InstallPlan / apt: "what is about to happen" inspectable before apply; stale plan "looks deliberate" | plan = print line |
| Generations by **copy**, 20 kept; rollback = config only | `:1829-1839`, `:1864` | Nix insight; symlinks unreliable on Windows; "volumes do not roll back" said honestly | symlink swap |
| Routing is an `-f` overlay, not an `include` | `:1920-1925` | `include` requires disjoint service sets; `-f` merges | labels inside includes |
| Overlay order is load-bearing (connections, then cpu-budget last) | `:960-975` | later file wins; connections blanks env; cpu caps lowered to host | alphabetical |
| Bootstrap recreate trigger = digest label of its inputs; compiled blueprint **excluded** | `:1005-1060` | compose config hash didn't move on blueprint content → 15 h unserved; including the compiled file cost 4 min 22 s per app toggle (now 30 s) | always recreate / never recreate |
| LF everywhere + no-op on identical bytes | `:913-945` | Windows render produced CRLF → artifact hash depends on who built it; watchers can't tell rewrite from change | `write_text` default |
| Company slug computed at render and written back into `.env` under a marker | `:63-88`, `:156 sync_identity` | compose cannot lowercase/substitute; render precedes every compose use; scope limited to marked lines | bootstrap script |
| Host split from port at render (`traefik_host`) | `:135-153` | traefik v3 `Host()` ignores the request port; compose can't split strings | `${VAR}` passthrough |
| Remote plane emitted into traefik **file** provider; backend = alias on link proxy | `serve.py` header | docker labels cannot point outside the engine ("port is missing"); tunnel address unreachable from `traefik-network` | labels; tunnel IP |
| `remote:` block arrives only via projection; validated before write; empty stdin ≠ `[]` | `:441-490`, `:2330-2350` | a bad peer catalog must not break every compile here; empty stdin erased the block once (2026-10-05) | SSH-run writer |
| `ensure_state` three answers, default refused on a compiled checkout | `:526-568`; `platform.state.default.yaml` header | git carried one office's runtime; a pull reset another office | one tracked state file |
| Catalog = F-Droid index-v2: signed index file, Ed25519, `.catalog/` not under `.generated/` | `catalog.py:1-60` | offline, mirrorable, no control plane; generations ×20 would multiply tens of MB | API-backed store; JAR signing |
| `enabled-apps` is the resolved **closure**, not the declared disposition | `:2535-2555`; release-plan Part 2 | `run_app_hooks` must act on what will run (supabase pulled in by indox) | declared list |
| bbox names no app: `bbox <id\|alias> <verb>` → `hooks/<verb>`; help generated | `bbox:354-412`, `:1040-1077` | adding an app meant editing the CLI in three places; `cli.alias/fallback` declared in the manifest | per-app `case` |
| Hooks: an app declares a need by **having a file**; must be executable in git | `lib.sh:1052 run_app_hooks`; G31 | seven 100644 hooks were inert on Debian; `/mnt/c` lies about modes | functions in bbox |
| `run_app_hooks` never stops early, returns a count | `lib.sh:1052-1078` | "a verification that cannot fail is not a verification" | `\|\| say` swallow |
| `BBOX_COMPOSE` is a path, not `docker compose` | `lib.sh` ~:350 | plugin search resolved to Docker Desktop's binary | fallback chain |
| Private engine socket; CLI and container socket must agree | `lib.sh:188-262`; `bbox:65` | a missing bind source becomes a **directory** → traefik healthy, 0 routers | `/var/run/docker.sock` |
| Repo mounted at the same path inside containers | `lib.sh` `BBOX_REPO_HOST` | docker invented a phantom `/repo` tree | path translation |
| Perf profile = richest `requires:` envelope the machine satisfies; floor on failure | `perf-profiles.yml`; `select-profile.py`; `bbox:221-268` | cores-only chain sized a 9.7 GiB VM as `prod`; 42 WSL teardowns/day | `if mem > X` branches |
| `up -d --build` by default | `bbox` ~:600-640 | `git pull && bbox run` otherwise serves the old image | pull-only |
| G1 byte-equivalence gate **deleted**, property gates instead | `GATES.md:570-636` | render is not reproducible (fresh secrets, absolute paths); 118 KB diffs rubber-stamped | re-golden |
| A gate exists only for a defect that "broke once and nothing noticed"; one list, `--verify-ci` | `GATES.md:1-6`; `scripts/ci/gates.sh:1-20` | two enumerations had drifted; baseline ran none | nice-to-have checks |
| Go port: stdlib-only, `CGO_ENABLED=0`, own YAML 1.1 subset, Python as oracle, `DGO_COMPILER=python` per-verb rollback | `packaging/dgo/main.go`, `internal/yamlish/yamlish.go:1-16`, `internal/compiler/catalog.go:1-13` | owner's constraint; a YAML 1.2 lib answers `on`/`0755`/`1e5` differently from PyYAML | yaml.v3; big-bang rewrite |

## 3. Invariants and one-owner rules

| Fact | Owner | Enforced by |
|---|---|---|
| `platform.state.yaml` format and every write | `reconcile.set_disposition` (apps), `set_office`, `set_remote` (+ `set_network` in the uncommitted diff) — all in the compiler, exposed as `set-state / office-set / remote-set` | **G33** `state-writer-lint`; 19 `set-state` call sites from 6 surfaces (core-native-plan §6) |
| What runs | `enabled_ids` / `resolve` / `enabled-apps` | G31 (layer 0 asks, never globs) |
| `.generated/` | written only by `render`/`compose_files`; header "GENERATED — DO NOT EDIT"; gitignored (`.gitignore:123`); archived to `generations/NNNN` before each render, 20 kept | `ensure_generated_writable` repairs root-owned trees (lib.sh:950) |
| The directory is the layer | `CATALOG_ROOTS` (:44); loader FATALs | G9 (base never names app), G31 (layer 0 names none) |
| Which `-f` files are the stack | `compose_files()` | G7 (no bare `docker compose`), G32 (no engine bypass) |
| Capability → provider | `resolve` (binding → default → sole); `capability-provider` verb for singletons; ambiguity is an error | G17 `test_resolve.py` (44 tests at HEAD), G25 |
| Which profile this machine gets | `select-profile.py` from `requires:`; budgets by G30 (memory) and G65 (CPU) | G30, G65 |
| Container creation | compose via `scripts/dc`/`dcx`; `BBOX_COMPOSE`, `BBOX_DOCKER_SOCK`, `BBOX_REPO_HOST` | G7, G32 |
| App bootstrap / first-run | `<root>/<id>/hooks/prepare\|onboard`, mode 100755 in git | G31 |
| Desired → actual | `app-management.reconcile_once()` via `POST /api/reconcile` | `ensure_converged` on every `bbox run` |
| A disposition parse | `reconcile.disposition()` — both shapes, no fallback copies | A1 (consolidation doc) |
| Product default vs office runtime | `platform.state.default.yaml` (tracked, never written) vs `platform.state.yaml` (runtime) | G23 judges the default; `ensure_state` refuses silent reset |

## 4. Pain points and smells — with evidence

| Smell | Evidence |
|---|---|
| **One 3,200-line file is loader + validator + resolver + 8 renderers + 20 verbs + 4 state writers + an `.env` mutator** | committed 3,219 lines, 71 commits, 31 since 2026-09-01; dirty tree **3,521** (+304: `network_block/validate_routes/set_network/office_lan_route/render_network_facts/lan_door_labels`). `render()` also mutates `.env` (`sync_identity`) and shells out to `git` (`ensure_state`) — the "pure function" is no longer pure. |
| **Duplicated knowledge bash ↔ python** | `.env` reference resolution: `lib.sh:41 read_env` and `reconcile.py:105 _envfile_value` (same 20-iteration rule, two languages); node lookup `bbox_node` vs `n8n_blueprint._node()` ("two languages, one rule" admitted inline); `bbox:354 app_resolve` is inline Python; `perf-profile-apply` and `select-profile.py` each hand-roll a YAML parser (consolidation §6); `packaging/make-runtime-compose.py` hardcodes the 3-file list `compose_files()` owns (A8, open); `cn()` container naming (lib.sh:994) re-derives `<svc>-<DN>` outside the compiler. |
| **Python-on-host is on the hot path** | `bbox` has 33 `python3` invocations, `lib.sh` 15; **every** `dc` call runs the compiler twice (`compose_args`: render-if-missing + `compose-files`); `run_app_hooks` runs `enabled-apps`; `ensure_converged`/`ensure_sso_current` each run `capability-provider`. Native Go answers 0.13 s vs 0.63 s per verb (core-native-plan). Rendering on every verb is also why `write()` had to become a no-op on identical bytes. |
| **Three host hand-offs, each with its own failure class** | `bbox.cmd` → WSL (`wslpath`, trailing-backslash quoting trap, Task Scheduler keep-alive); macOS → Lima guest (`engine.sh exec`, `agent` verb kept on host for latency); cloud sandbox: 5 `ccr_*` helpers (CA shadow, nofile clamp, serial builds, registry hint). `/mnt/c` reports 755 → 7 inert hooks (release-plan Part 2); CRLF from Windows Python → `tr -d '\r'` in `compose_args`; `npath` on every argument (G10). VPS parity "still the largest untested surface" (G3.3). |
| **Gate count and what it says** | `GATES.md` records **81 gate numbers** (G0-G86; 51/57/66-69 never assigned; 5 rows unassigned/retired); `scripts/ci/gates.sh` runs **64**; `scripts/refactor/` holds **80** `*-lint.py`. Most gates past G35 police n8n workflow *content* (G36-G53) — app-domain invariants enforced by regex over JSON, not by a type system or the compiler. The registry itself needed a gate (`--verify-ci`) and a renumbering (three numbers used twice). Gates read green with blind spots (G62 scanned 47/209 files; G44 saw 1 of 8; G9 green without `--strict` for months; G53 **known failing**). Correctness here is *lint-shaped*: asserted after the fact, not made unrepresentable. |
| **State-file write races** | All writers are regex/text surgery with no lock or atomic rename (`STATE.write_text`, :289/:431/:490); `set_remote` cuts and re-appends the whole tail; the projection would rewrite every minute until `fetched` was excluded; `set-state` is called from `bbox`, app-management, dgo-extend `converge/move/migrate`, `quiet-mode.sh`, `qa-fix-loop.sh`, **and the office agent's config**. `.env` already suffered a concurrent-writer truncation (dc guard, 2026-07-29) — `platform.state.yaml` has no equivalent guard, only the one-writer gate. `ensure_state`'s `ORIG_HEAD` heuristic reads git history to decide runtime state. |
| **Dirty-tree hazard** | Three writers share this checkout; `bbox run` uses `--build`, so **a live rebuild ships whatever is uncommitted**; `compose_args` renders on every `dc`, so an uncommitted compiler edit (today's +304) runs under every verb of every writer before review. `.claude/worktrees/` holds three full copies, each grep'd as "the repo" by naive tooling. |
| **Validation is bespoke on both sides** | `validate()` enforces only what it hand-codes; schema `pattern/minimum/minItems/oneOf/additionalProperties` below top level are "documentation" — and the Go port **copies the gap by design** ("the contract is reconcile.py's behaviour, not the schema's"). |
| **Convergence reaches into a container** | `ensure_converged` runs `docker exec <control-plane> python3 -c 'urllib…'` against the container's own HTTP API and parses a 500 from stdout text. |
| **Open debts the docs already name** | A2, A6, A7 (`N8N_CONTAINER/PG_CONTAINER`: 84 refs/18 files), A8, G3.3 VPS parity, cgroup v1/v2 alternation across WSL restarts, shared default secrets in `.env.ex` (G5.2, owner: keep). |

## 5. The Go port — what `packaging/dgo` has absorbed and how it is verified

| Piece | State | Size | Proof |
|---|---|---|---|
| `dgo` CLI (`main.go`) | finds the checkout (needs `reconcile.py` **and** `bbox`); 20 compiler verbs delegated to Python with args untouched; app dispatch `<id\|alias> <verb>` → `hooks/<verb>` in bbox's order (bare, `.sh`, `.py`, `.mjs`); Windows → `bbox.cmd`; everything else → `bbox`; `DGO_ROOT/DGO_VERSION` exported | 336 lines | 10 tests (`dgo_test.go`): root discovery, verb listing, hook resolution, delegation argv, alias, Windows hand-off |
| `internal/yamlish` | PyYAML-1.1 subset reader (block/flow maps + seqs, quoted/block scalars, comments, one `---`; **refuses** anchors/aliases/tags/merge keys/multi-doc); insertion-ordered `Map`; `encode.go` = `safe_dump` emitter (**untracked in the tree**) | 870 + 333 + 364 lines | `TestCorpusMatchesPyYAML` — PyYAML run beside it on every file the compiler reads, canonical JSON byte-identical (56/56); `TestMarshalMatchesPyYAML`; `TestRefusesWhatItDoesNotSpeak` |
| `internal/compiler` | `LoadCatalog` (FATAL sentences verbatim), `LoadState` (`ensure_state`'s three answers, both disposition shapes, legacy id), `Resolve` (every rule, same diagnostics), `Validate` (check-for-check incl. Python quirks: bool-is-int, explicit null fails), verbs `validate` + `enabled-apps` **native** | 195+179+293+418+88 lines | **Oracles on the real checkout**: `TestEnabledAppsMatchesPython` (same stdout bytes, exit code, error-line set), `TestValidateMatchesPython`; plus one synthetic fixture per resolver/validator rule (12 + 10 tests). Tests `t.Skip` when no Python+PyYAML is on PATH. |
| Rollback | `DGO_COMPILER=python` delegates a native verb back | — | `plan()` honours it before `nativeVerbs` |
| Not ported | `compose-files`, `render` (the emitter), `set-state`, `plan/apply`, generations, serve plane, the `.env` mutation; engine provisioning; control plane (step 3); console server (4); credential plane (5) | — | core-native-plan §3 steps 1b-7; `render` must be byte-identical to `.generated/` |
| Sibling natives | `packaging/installer` (11 tests), `platform-base/forward-auth` (28 tests, held before cutover) | 5.3 / 7.8 MB | `packaging/build-binaries.sh`: 6 OS/arch, double build proves reproducibility, `SHA256SUMS`, Ed25519-signed download tree |

Total Go in `packaging/dgo`: ~4,200 lines, `go 1.22`, no module dependencies. **41 Go tests**, three of which are differential oracles against the live Python; Python side keeps 44 (`test_resolve.py`) + 8 (`test_office.py`) tests as the behavioural spec.
