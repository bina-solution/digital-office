# Operating «מכונה» (the `machine` app)

The office machine's numbers: CPU, memory, disk, the containers and their use, what can be cleaned,
and the power policy. Its screen lives inside «מחשבים» now (the computers app draws it), so it has no
tile of its own. The `/a/machine/` door stays because the console's power card and
`bbox computers herd` read it. It reads the host through a read-only mount of `/` and the docker
socket.

## From inside the office network (`http://machine:8080`)

```bash
GET /api/overview            # the host and its containers: CPU, memory, disk, per-container use
GET /api/storage             # what holds the disk: images, volumes, build cache
GET /api/cleanup/options     # what cleanup could free, and which actions this office allows
GET /api/power               # the power policy, and the host's own power facts
POST /api/cleanup/<action>   # docker_container_prune | docker_image_prune_dangling |
                             # docker_image_prune_all | docker_builder_prune_all
PUT /api/power/policy        # {lock|lid: {ac|battery: run|sleep}, battery_floor: 5–90, thermal_guard}
```

Over a link: `./bbox remote <office> machine /api/overview`. From the shell, the same reads:
`./bbox machine overview|storage|cleanup-options|power`; they change nothing. The Mac's own engine
has `./bbox engine power status`.

## Rules

- Reading is free, and it is how you check load and disk before a build.
- **Cleanup prunes the whole engine**: every stopped container, every unused image, or the build
  cache.
  - It answers 403 unless the action is in `MACHINE_CLEANUP_ALLOWED_ACTIONS`, which is empty by
    default.
  - Never add an action to that list or run one without the owner's words. A pruned image is a
    rebuild, and a stopped container may be someone's paused work.
- **The power policy decides whether the machine may sleep.** On the Mac, the power agent enforces
  it: "sleep" lets the lid put the Mac to sleep, and a sleeping Mac freezes its engine and every
  agent on it.
  - The default is "run". Never set "sleep" unless the owner asks.
- Nothing here powers off or reboots the host.

## Traps

- The whole host root is readable from this container. Read what the task needs and nothing more.
- `app.json` declares 384M but the compose allows 640M. The apps screen's room check reads
  `app.json`.
- The VM host facts (`data/power/host.json`) are ignored once they are 15 minutes old.

Gates: G27 (the shared screen blocks).
