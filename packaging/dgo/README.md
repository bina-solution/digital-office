# dgo — the office's one binary (step 1 of [the core-native plan](../../ai/context/core-native-plan.md))

```bash
cd packaging/dgo && go test ./... && go build -trimpath -ldflags "-s -w" .   # stdlib only, CGO_ENABLED=0
./dgo help                 # generated from the tree: the compiler's verbs, every app's hooks
./dgo validate             # a compiler verb answered NATIVELY (internal/compiler) — byte-identical to reconcile.py, 5× faster
./dgo enabled-apps         # native too (validates the manifests first, as reconcile.py's main() does)
./dgo render               # a compiler verb not ported yet — delegated to platform/manager/reconcile.py
DGO_COMPILER=python ./dgo validate   # the per-verb rollback: delegate a native verb to Python again
./dgo indox test           # an app's verb — its hooks/test, by id or by the manifest's cli.alias
./dgo run                  # everything else is handed to bbox, until dgo absorbs it
```

On Windows only the compiler's verbs run natively; an app's verb and `run` go through `bbox.cmd` —
the hand-off into the project's own WSL engine, where the office actually is.

What this slice guarantees: the names, arguments and exit codes the plan's §6 measured are answered
as they are; `DGO_ROOT` and `DGO_VERSION` reach every child. What it does not do yet: provision the
engine (`bbox.cmd` / `bbox engine`), compile, or serve — those are steps 1b–5.

Cross-compile for every OS from one host: `GOOS=windows|darwin|linux GOARCH=amd64|arm64 go build .`

The release build is `bash packaging/build-binaries.sh <version>` — this binary, the installer stub and
forward-auth for all six targets, vetted and tested, reproducible (proven by a double build), with
`SHA256SUMS` and the download tree the installer verifies; `.github/workflows/release-binaries.yml`
runs it on a `v*` tag. Details in [packaging/installer/README.md](../installer/README.md).
