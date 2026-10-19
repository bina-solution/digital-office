# A symlinked spelling of REPO_ROOT emptied every relative bind mount

**Measured 2026-10-01, this checkout, live. Fixed 2026-10-02 in `32ddb392`.**

Every app that bind-mounts the compiled registry got an **empty directory** — and nothing said so:
the container was healthy, the app started, and the only symptom was missing data.

## The defect

`scripts/dc` runs compose from `REPO_ROOT` with `--project-directory .`, and each app declares the
compiled registry **relatively** (`../../.generated/registry`). Compose resolves that relative source
against the project directory — *as spelled*.

Inside `bina-ds` the checkout is reached through `/workspace/office`, a **symlink**. The engine does
not resolve that spelling for a bind source: it treats it as a literal path it must have, finds it
absent, **creates it as an empty directory**, and mounts that. Measured:

```bash
$ docker inspect console-local --format '{{range .Mounts}}{{.Source}} => {{.Destination}}{{"\n"}}{{end}}'
/workspace/office/.generated/registry => /app/generated     # a path the Docker host does not have
$ docker exec console-local ls /app/generated | wc -l
0
$ ls /workspace/office/.generated/registry | wc -l          # inside the container: the real files
8
```

The same command from the host shell named the physical path (`/Users/…/שלי /.generated/registry`) and
bound correctly — which is exactly why this looked like a host-specific quirk and hid for so long.

**The fix (`32ddb392`, `scripts/lib.sh`):** `REPO_ROOT` is taken with `pwd -P`, so both entry points
(`bbox` and `scripts/dc`) hand compose the physical directory. From inside `bina-ds` and from the host
the same `./scripts/dc up -d <app>` now names the same real path.

## What it broke

* `console` — `/app/generated` empty → `/api/modules` fell through to the two built-in views and the
  rail rendered **2 rows instead of 13**: `console.modules.yaml`, the office registry and the peer
  plane's records were all invisible. The console kept answering `200` and rendering a full page, so
  no healthcheck could see it.
* `app-management` — `/repo` and `/app/generated` both empty → "0 אפליקציות" and a failing registry
  read, on a host where 15 apps are installed.
* `connections` — the same mount, same source line (`platform-base/connections/docker-compose.yml:47`);
  same source, not separately measured.
* `dgo-extend` — `/registry` (its `office.apps.json`) likewise.

## What it did NOT break

Named volumes, and mounts written with an **absolute physical** path — `bina-ds` mounts the checkout
at its real path and saw every file. That is why the agent's own container was fine while the platform
it was operating on was not.

## A wrong first diagnosis, recorded on purpose

This file was written as "the repo path ends with a space and compose trims it". **That is not what
happened.** The path does end with a space, and a source spelled with **two** trailing spaces was
observed once — but the working comparison was never the trailing space: it was *symlink spelling
versus physical path*. The first write-up named the first difference it could see instead of the one
that mattered, and the giveaway was in its own evidence (`/workspace/office/...` as the mount source).

The lesson worth keeping: when a mount lands on an empty directory, print the **source the engine
recorded** (`docker inspect … .Mounts`) and compare it character by character with `pwd -P` — not with
the path the shell happens to be sitting in.
