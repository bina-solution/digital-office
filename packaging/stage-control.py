#!/usr/bin/env python3
"""stage-control — copy the MINIMUM tree the platform needs at runtime into a staging dir.

    python3 packaging/stage-control.py --dest /tmp/stage/platform

The first cut of the Linux installer shipped `tar -c apps platform-base compose.yml`, which is
125 MB — and 1033 of its entries are `apps/apitools`, 454 are `apps/n8n`, 378 are
`apps/indox`. That is application SOURCE, and it is already compiled into the images the bundle
carries. Shipping it is wasteful, and it hands the customer a copy of the source for no reason.

What the running platform actually needs on disk is narrow and derivable:

  * the compiled compose output (`.generated/*.yml`) — what `docker compose` is invoked with
  * every app's `docker-compose.yml` and `app.json` — the compiled file `include:`s them by path
  * every app's `hooks/` — app-management shells out to these at install/enable/disable time
  * `platform.state.yaml` and `platform/` — app-management edits the state file and runs the
    compiler in-process; the control plane genuinely needs them at runtime
  * every RELATIVE BIND-MOUNT SOURCE named by any compose file — kong.yml, the authentik
    blueprints, supabase's init SQL, n8n's workflows. These are read from the host at container
    start, so a missing one is a service that fails to boot.

Everything else — Dockerfiles, src/, tests, fixtures not bind-mounted, fonts, node_modules — is
build input, not runtime input.

Bind sources are DISCOVERED from the compose files rather than listed here, because a hand-written
list is a second source of truth that goes stale the moment an app adds a mount, and the failure
mode is a container that will not start on the customer's machine.
"""
import argparse
import os
import pathlib
import shutil
import sys

try:
    import yaml
except ImportError:
    print("stage-control: pyyaml required", file=sys.stderr)
    raise SystemExit(2)

REPO = pathlib.Path(__file__).resolve().parents[1]

# Per-app files that always travel.
APP_FILES = ("docker-compose.yml", "app.json")
APP_DIRS = ("hooks",)

# Repo-level paths the control plane needs at runtime. BOTH desired-state files: the office's own
# (a staging image carries it so it can come up as this deployment) and the tracked default beside it
# (what `reconcile.ensure_state()` creates from when a checkout has neither) — see the default's header.
ROOT_PATHS = ("platform.state.yaml", "platform.state.default.yaml", "compose.yml", "platform",
              ".generated/compose.yml", ".generated/routing.override.yml",
              ".generated/connections.override.yml", ".generated/resolved.json",
              ".generated/compose.runtime.yml")

# Never recurse into these, wherever they appear. `.generated/generations` holds up to 20 archived
# copies of the whole compiled output — rollback history that is meaningless on a fresh install.
PRUNE = {"node_modules", "__pycache__", ".git", ".venv", "generations", ".pytest_cache"}

# Data directories that are bind-mounted but whose CONTENTS are runtime state, not shipped input.
# They must exist or the mount creates a root-owned directory; they must be empty or we ship the
# dev machine's logs and uploads to the customer. `data` covers the per-app data dirs —
# chat's holds `subscribers.db`, which is real customer data and must never leave
# this machine.
EMPTY_DIRS = ("logs", "storage", "data", "data/browser42")

RUNTIME_COMPOSE = pathlib.Path(".generated") / "compose.runtime.yml"


def bind_sources():
    """Every relative bind-mount source the COMPILED compose will actually mount.

    Read from the compiled compose, not from the source `docker-compose.yml` files. Globbing the
    sources missed two whole categories, because a service's mounts are not all declared in its own
    compose file:

      * `platform/profiles/connections-mode.yml` and `apps/*/connections.override.yml` add the
        `inject.sh` mount to a dozen services. Neither filename matches `docker-compose.yml`, so
        `inject.sh` was never staged and every consumer died with
        `bind source path does not exist`.
      * `${WHATSAPP_DATA_DIR:-./data}` is a variable. Interpolation happens during compilation, so
        only the compiled file names the real path.

    The compiled compose is what the customer runs, so it is the only listing that cannot drift
    from reality.
    """
    doc = yaml.safe_load((REPO / RUNTIME_COMPOSE).read_text(encoding="utf-8")) or {}
    out = set()
    for svc in (doc.get("services") or {}).values():
        for vol in (svc.get("volumes") or []):
            if isinstance(vol, str):
                src = vol.split(":")[0]
            elif isinstance(vol, dict) and vol.get("type") == "bind":
                src = vol.get("source")
            else:
                continue
            if not src or not src.startswith("./"):
                continue      # absolute (/var/run/docker.sock) or a named volume — not ours to ship
            rel = pathlib.Path(src[2:])
            if str(rel) in (".", ""):
                # app-management mounts the project root so it can write platform.state.yaml and run
                # the compiler. The staged tree IS that mount — copying "." into itself recursed the
                # whole repo (3.5 GB) instead of the ~2 MB actually needed.
                continue
            out.add(rel)
    return out


def is_empty_dir_target(rel: pathlib.Path) -> bool:
    s = rel.as_posix()
    return any(s == d or s.endswith("/" + d) for d in EMPTY_DIRS)


def copy(src: pathlib.Path, dest_root: pathlib.Path, rel: pathlib.Path, stats):
    dest = dest_root / rel
    if not src.exists():
        stats["absent"].append(rel.as_posix())
        return
    if src.is_dir():
        if is_empty_dir_target(rel):
            dest.mkdir(parents=True, exist_ok=True)
            stats["empty_dirs"] += 1
            return
        dest.mkdir(parents=True, exist_ok=True)
        for item in src.rglob("*"):
            if any(p in PRUNE for p in item.parts):
                continue
            if item.is_file():
                target = dest / item.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                stats["files"] += 1
                stats["bytes"] += item.stat().st_size
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        stats["files"] += 1
        stats["bytes"] += src.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True, type=pathlib.Path)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    dest = args.dest
    dest.mkdir(parents=True, exist_ok=True)
    stats = {"files": 0, "bytes": 0, "empty_dirs": 0, "absent": []}

    if not (REPO / ".generated" / "compose.yml").is_file():
        print("stage-control: no .generated/compose.yml — run 'bbox reconcile' first", file=sys.stderr)
        return 1
    if not (REPO / RUNTIME_COMPOSE).is_file():
        print(f"stage-control: no {RUNTIME_COMPOSE.as_posix()} — run make-runtime-compose.py first",
              file=sys.stderr)
        return 1

    for name in ROOT_PATHS:
        copy(REPO / name, dest, pathlib.Path(name), stats)

    for root in ("apps", "platform-base"):
        for appdir in sorted((REPO / root).iterdir()):
            if not appdir.is_dir():
                continue
            rel_app = pathlib.Path(root) / appdir.name
            for f in APP_FILES:
                copy(appdir / f, dest, rel_app / f, stats)
            for d in APP_DIRS:
                copy(appdir / d, dest, rel_app / d, stats)

    binds = bind_sources()
    for rel in sorted(binds):
        src = REPO / rel
        if not src.exists():
            # Named by the compose but absent here: a runtime directory the dev machine happens not
            # to have created yet. Docker will not invent it — a bind whose source is missing is a
            # hard `docker compose up` failure — so ship it as an empty directory.
            (dest / rel).mkdir(parents=True, exist_ok=True)
            stats["empty_dirs"] += 1
            continue
        copy(src, dest, rel, stats)

    # Every mount the customer's compose names must be present in the tree we are about to seal.
    # Without this the build happily produced an artifact that installed cleanly and then failed at
    # `systemctl start` with `bind source path does not exist` — one service at a time, so each
    # rebuild revealed exactly one more. Checking the whole set here turns that into one message.
    missing = sorted(r.as_posix() for r in binds if not (dest / r).exists())
    if missing:
        print("\nstage-control: FAIL — the compiled compose mounts paths that are not in the tree\n",
              file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        print("\nEach one fails `docker compose up` on the customer's machine with:",
              file=sys.stderr)
        print('  invalid mount config for type "bind": bind source path does not exist',
              file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"staged {stats['files']} file(s), {stats['bytes']/1e6:.1f} MB, "
              f"{stats['empty_dirs']} empty data dir(s), {len(binds)} bind source(s) - "
              f"all present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
