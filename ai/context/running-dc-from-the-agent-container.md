# Running `./scripts/dc` from the agent container — the mount that silently goes empty

Written 2026-10-01, after it cost a session. Short version:

> **Run container-recreating `dc` commands from the checkout's PHYSICAL path.**
> `cd "$(cd /workspace/office && pwd -P)" && ./scripts/dc up -d --build <svc>`

## What happens if you do not

`/workspace/office` is a symlink to the real checkout (the path with the Hebrew name). A `cd` into it
keeps the LOGICAL path, so:

```bash
cd /workspace/office && ./scripts/dc up -d --build console
```

runs `docker compose --project-directory .` with `.` = `/workspace/office`, and every **relative bind
mount** in the compiled stacks is resolved against that directory. The engine, however, is the host's
— `/workspace/office` exists inside the agent container and *not* on the engine's side. Docker creates
that path on the engine side and the container gets it **EMPTY**. No error, no warning:

- the console's `/app/generated` (`.generated/registry`) arrives empty →
  `_app_bases()` falls back to its hardcoded map → **every** `/a/<alias>/` answers
  `{"error":"unknown_app"}`, i.e. the whole office stops embedding apps;
- `healthz` keeps answering **200**, the container reports healthy, and the only symptom is that
  every tile is broken.

Named volumes (`dgo_extend_state`, …) and paths baked into an image are unaffected, which is why
`--build dgo-extend` / `mailview` / `git` looked fine while `console` did not.

`npath()` in `scripts/lib.sh` is a no-op on Linux, so it does not save you here — the scripts that
matter already use absolute paths derived from `pwd -P` (`run_capture.sh` mounts `$(npath "${DATA}")`
where `DATA` came from an absolute path).

## How to notice you already did it

```bash
for c in $(docker ps --format '{{.Names}}'); do
  docker inspect -f '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}}{{"\n"}}{{end}}{{end}}' "$c" \
    | grep '^/workspace/' && echo "  ^ $c has a bind mount the engine cannot see"
done
```

Any hit under `/workspace/` is a mount that came from inside the agent container. Re-run the same
command from `pwd -P` and the container is recreated correctly.

## The sibling trap in the same shape

`ui-map` / `dgo55-score.sh` draw the same conclusion for their own mounts — a capture that starts
with

```
FATAL: /data/ui-inventory.json missing in container — the /workspace/office/data/ui-map:/data bind
mount did not carry through
```

is this exact fault, and the fix is the same `cd "$(pwd -P)"`. A capture that "ran fine" from the
logical path scores **stale** results from the previous run's `data/ui-map`, which is how a
measurement can look green and be about a screen nobody captured.
