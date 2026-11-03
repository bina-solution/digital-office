# Binary-release machinery — measured state (2026-10-14)

Read-only audit of `hp-dgo` @ `7347f738`, Go 1.22.3 native on Windows, no WSL/Docker. Builds and logs
sit beside this file (`bin/`, `test-*.txt`, `validate-*.txt`, `enabled-*.txt`). Plan reviewed:
`origin/vps1-dgo:ai/context/binary-release-plan.md`; **the packaging Go code is byte-identical on both
branches** (empty `git diff --stat`), so the plan describes exactly this code.

## 1. Tests — `go vet ./... && go test ./... -count=1 -v`

| module | vet | tests | result | wall |
|---|---|---|---|---|
| `packaging/dgo` (3 pkgs) | OK | 41 | **39 pass, 2 FAIL** — both in the *untracked* `internal/yamlish/encode_test.go` (another session's WIP) | dgo 2.3 s · compiler 10.4 s · yamlish 53.2 s |
| `packaging/installer` | OK | 12 | 12 pass (plan says 11) | 14.7 s (13.1 s = `TestRelsignSignatureVerifiesInGo`, which `go run`s relsign) |
| `packaging/relsign` | OK | 6 | 6 pass | 1.1 s |
| `platform-base/forward-auth` | OK | 28 | 28 pass | 5.8 s |

Oracle tests ran against real Python 3.12 + PyYAML 6.0.3: `TestEnabledAppsMatchesPython` 4.1 s,
`TestValidateMatchesPython` 2.7 s, `TestCorpusMatchesPyYAML` 56/56 files 40 s. Tree untouched
(`platform.state.yaml` clean; `ensureState` writes only when the file is missing).

The two WIP failures: (a) `TestMarshalMatchesPyYAML` — one long plain scalar folds one word later than
PyYAML (width off by one); (b) `TestMarshalRoundTripsThroughUnmarshal` — a harness bug (`mustYAMLFromJSON`
wraps the document in `v:`) plus PyYAML-1.1's own `1e-05` float/string asymmetry. All *tracked* yamlish tests pass.

**CI reality:** only `release-binaries.yml` (tag `v*` or manual dispatch) runs `go vet/test`; no push-time
workflow does. **No `v*` tag exists** — the lane has never fired on a tag; no release artifact exists anywhere.

## 2. Binaries — `CGO_ENABLED=0 go build -trimpath -ldflags "-s -w"` (plan 1.4: ≤ 5,242,880 B)

| binary | target | bytes | over 5 MiB? |
|---|---|---|---|
| dgo-install | windows/amd64 (`dgo-install.exe`) | **5,327,872** | **yes, +84,992** |
| dgo-install | darwin/amd64 | 5,287,104 | **yes, +44,224** |
| dgo-install | linux/amd64 | 5,169,304 | no |
| dgo-install | darwin/arm64 | 5,064,226 | no |
| dgo-install | windows/arm64 | 4,981,760 | no |
| dgo | windows/amd64 (`dgo.exe`) | 2,575,872 | — |
| dgo | linux/amd64 | 2,453,656 | — |
| forward-auth | windows/amd64 | 7,650,816 | — |
| forward-auth | linux/amd64 | 7,405,720 | — |

The stub's weight is stdlib `net/http`+TLS (the 2.5 MB `dgo` has neither); `-s -w` is already the
default, so the two amd64 desktop targets need UPX or a smaller HTTP path.

## 3. Behaviour measured (binaries run from the scratchpad)

| run | result |
|---|---|
| `dgo-install.exe`, no flags (= a double-click) | prints the terms, exit 1 `terms not accepted — re-run with --accept-terms`. No prompt, language or screens. |
| `dgo-install.exe --accept-terms --no-launch` (template) | exit 1, fail-closed `unconfigured template build`; no `dest` created. Correct. |
| `dgo.exe help` outside a checkout | **exit 2 `not inside a DGO checkout (no platform/manager/reconcile.py + bbox above here)`** — what the downloaded `dgo-core` does on a fresh machine. |
| `dgo.exe validate` / `enabled-apps` in the tree | byte-identical to `reconcile.py` (43 manifests / 24 lines). Warm: validate 0.5–1.5 s vs Python 1.4–3.1 s; enabled-apps 1.5–1.9 s vs 4.1 s. |
| `forward-auth.exe`, no env | exit 1, refuses without `FORWARD_AUTH_EXTERNAL_URL, _SECRET, _ALLOWED_HOSTS`. |

## 4. Plan vs reality

### Part 1 — the loader

| # | item | state | where | test? |
|---|---|---|---|---|
| 1.1 | Ed25519 key; public half baked into every stub | **partial** — machinery complete (`relsign keygen/pubkey/sign/manifest/verify`; `--sign-key` bakes `-X main.pubKeyB64` + per-target `manifestURL`; CI secret `DGO_RELEASE_KEY`); **no key, secret or tag → drafts only** | `relsign/main.go`; `build-binaries.sh:118-123,170-181`; `release-binaries.yml:57-70` | yes — 6 relsign tests, `TestRelsignSignatureVerifiesInGo`, `--selftest` |
| 1.2 | manifest host `digital-office.co.il/dl/<os>/<arch>/manifest.json` | **absent** — a default string; `dist/dl/` tree is produced but nothing serves it | `build-binaries.sh:53`; `installer/main.go:16` | fetch path only (httptest) |
| 1.3 | first-run screens (language, terms, confirm, location; Enter-only); `~/.bina/config.yaml` | **absent** — flags only (`--accept-terms`, `--dest`), text terms, no prompt, writes only `VERSION` | `installer/main.go:65-99,137` | no |
| 1.4 | ≤ 5 MiB | **partial** — 3/6 under; windows/amd64 and darwin/amd64 over (table above); no size gate | `build-binaries.sh:143` | no |
| 1.5 | install without `git clone` — layer 0 as a signed archive | **absent** — payload is the single `dgo-core` binary = the `dgo` CLI shim, which requires the checkout **and** python3+PyYAML; no archive format, no `embed` anywhere in `packaging/dgo` | `installer/main.go:124-147`; `dgo/main.go:93-107` | `TestTheCheckoutIsFoundFromAnywhereBelowIt` asserts the *opposite* requirement |

### Part 2 — layer 0

| component | plan | measured |
|---|---|---|
| compiler | partial | **2 of 20 verbs native** (`validate`, `enabled-apps`), only with zero extra args (`main.go:116`); the other 18 `exec` `reconcile.py` (`python3 → python → py -3`); yamlish reader tracked, encoder **untracked WIP** |
| control plane (`dgo serve`) | absent | Flask, `platform-base/app-management/app.py` |
| console | absent | Flask container; nothing embedded in `dgo` |
| vault / connections | absent | Python, `platform-base/connections` |
| identity | written | Go, 28 tests, declared layer-1 app (`forward-auth/app.json`), image built by `images.yml`; **not wired** — `platform-base/traefik/config/authentik-forwardauth.yaml:36` still dials `authentik-server:9000`; users file must exist at `/var/lib/forward-auth` |
| network (`dgo-net`) | containers | `dgo-net` and `dgo-link` are compose services of the **dgo-extend Python image** (`apps/dgo-extend/docker-compose.yml:111,185`) |
| notifications | Python container | `platform-base/notifications/app.py` + gunicorn |
| extension (`dgo-extend`) | Python | `apps/dgo-extend/*.py` |
| engine decision | open | `dgo` provisions nothing: Windows → `cmd /c bbox.cmd` (`main.go:133-136`), else `bash bbox` |

### Part 3 — the store

| # | item | measured |
|---|---|---|
| 3.1 | signed package format + `package.yaml` | **partial, in Python** — `platform/manager/catalog.py`: F-Droid index-v2 model (`index-v1.json` + detached Ed25519 `index-v1.sig.json`, deterministic zip of `app.json`+compose+hooks, disclosure in the index); `bbox catalog keygen\|build\|verify`; `catalog_selftest.py`. No `package.yaml`. |
| 3.2 | public index + `dgo install` | **partial** — `bbox app install <id\|url\|path\|dir>` (`platform/manager/appinstall.py`: fetch → sha256 → safe unpack → validate → resolve → disclose → place+enable). No hosted index/CDN; `dgo` has no `install` verb. |
| 3.3 | dgo-net as a Go project | **absent** — exists only as the dgo-extend Python services |
| 3.4 | layer-1 blueprints / "install recommended" | **absent** |
| 3.5 | clean-machine gate on 3 OSes | **absent** for dgo-install; the *older BinaOS bundle lineage* has VM scripts (`packaging/windows/{provision,run}-test-vm.sh`, `test-in-guest.sh`) for the 2.2–2.5 GB `.run`/`wsl --import` artifact |

## 5. Gaps and risks in the code

1. **Payload ≠ layer 0.** `dgo-core` is the CLI shim; on a fresh machine it exits 2, so "download → verify → launch" always ends in an error. Nothing yields a running office from a download.
2. **No first run.** A double-clicked EXE prints and exits 1 (console flashes and closes). No GUI, PATH/Start-menu entry, service/launchd/systemd unit, uninstall or self-update; launch is `exec.Command(payload)` in the stub's foreground.
3. **Rollback/freeze protection is thin.** Forward-only compares against a user-writable plain-text `VERSION` file; the manifest has no expiry or sequence, so an old *correctly signed* manifest replays forever on a fresh machine. The signed message omits os/arch — a linux manifest at the windows URL yields a Linux `dgo-core.exe` (sha passes, launch fails): correctness, not security.
4. **TLS/proxy.** Stdlib client, default transport: system CA roots, honours `HTTP(S)_PROXY`, follows redirects (including https→http) — the same-host/https check runs on the *URL*, not the final hop; integrity still rests on sig+sha. No resume; `os.Create` truncates an existing `dgo-core`.
5. **Key lifecycle.** One key, no rotation/revocation path (pubkey baked into the stub); the CI key is `rm -f`'d from `RUNNER_TEMP`.
6. **Toolchains diverge.** `go.mod`/workflow pin 1.22; `forward-auth/Dockerfile` uses `golang:1.23-alpine` → image and released binary differ. Reproducibility proven for linux/amd64 only (`build-binaries.sh:152-159`).
7. **Delegation seams.** Native only when `len(args)==1` (`validate --x` silently goes to Python); `.py` hooks run via a literal `python3` (`main.go:247`); `reconcile.py` needs PyYAML on the host.
8. **forward-auth cutover** needs the traefik address swap, a users file and `FORWARD_AUTH_SECRET`; cookie-only sessions (revocation = rotate the key); `/login` is unthrottled at PBKDF2-210k per attempt.
9. **Untracked WIP** `yamlish/encode.go`: 2 failing tests — must not land as-is.
10. **Two lineages, no canonical one.** `packaging/README.md` describes the BinaOS bundle (`build-bundle.sh`, cosign, Inno Setup, `binaos.service`); the plan describes the native lane (`build-binaries.sh`, relsign); the Python signed catalog is a third, unnamed by the plan.

## 6. The three gaps that matter most

1. **No layer 0 to download** (1.5 / part 2): the lane's only payload is a shim that needs the whole repo, Python and bbox. Every part-1 item is downstream of this.
2. **No key, host, tag or CI gate** (1.1 / 1.2): the signing path is complete and tested, but nothing was ever signed or published, and `go test` never runs on a push.
3. **Part 3 is partly built — in Python**: `catalog.py` + `appinstall.py` already implement a signed F-Droid-style index and `bbox app install`; the plan budgets 3.1–3.2 as new Go work without naming them.
