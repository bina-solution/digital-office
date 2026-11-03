# dgo — the office's one binary (step 1 of [the core-native plan](../../ai/context/core-native-plan.md))

```bash
cd packaging/dgo && go test ./... && go build -trimpath -ldflags "-s -w" .   # stdlib only, CGO_ENABLED=0
./dgo help                 # generated from the tree: the compiler's verbs, every app's hooks
./dgo validate             # a compiler verb answered NATIVELY (internal/compiler) — byte-identical to reconcile.py, 5× faster
./dgo enabled-apps         # native too (validates the manifests first, as reconcile.py's main() does)
./dgo set-state --app x --state enabled   # the writers are native too — set-state, office-set, remote-set: reconcile.py's
                           # bytes, under the lock data/.locks/platform.state, the file replaced atomically
./dgo render               # native too — the whole of .generated/ (and traefik's zz-serve.yaml, authentik's
                           # zz-generated-apps.yaml) byte-identical to reconcile.py's; so are compose-files, serve-plan
./dgo plan                 # a compiler verb not ported yet (plan, apply, up, rollback) — delegated to reconcile.py
DGO_COMPILER=python ./dgo validate   # the per-verb rollback: delegate a native verb to Python again
./dgo be-child control --listen 127.0.0.1:7071   # the control plane on loopback: app-management's routes, the
                           # reads answered natively (internal/serve), the rest by its container; BBOX_CONTROL_PLANE=container: all
./dgo be-child console --static platform-base/console/static --upstream <the console container's URL>
                           # the console's server (internal/console), on 127.0.0.1:8000: the shell (one tree, read at start),
                           # /api/version and /api/modules as app.py answers them, the rest proxied to the container; needs
                           # GENERATED_REGISTRY, CONSOLE_PEERS_DIR, APP_MANAGEMENT_URL; identity believed only from --trusted-proxy;
                           # DGO_CONSOLE=container proxies everything (the rollback — it needs only --upstream). The release
                           # build (-tags consoleembed) carries the console's files as committed: --static is then optional
./dgo engine doctor|plan   # the engine, read the way bbox decides it (DGO_ENGINE=bbox hands it back)
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
runs it on a `v*` tag. Details in [packaging/installer/README.md](../installer/README.md). Its dgo carries
the console's files — platform-base/console's `static/` and `modules.yaml` as committed at HEAD — copied
into `internal/console/snapshot/` of a copy of this module, never here (the directory stays git-ignored).
