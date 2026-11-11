# Operating «סיגנל» (the `signal` app)

Signal Desktop, the official client, inside the office (ai/context/wrapped-official-app.md, DGO-1264): its
screen is the console's tile (Signal Desktop under Selkies, behind the front door), linked to the owner's
phone. Its database, its key and the link live in the volume `signal_home`. amd64 only: Signal ships no
arm64 Linux build, so it runs on the HP and vps1, not on the MacBook's engine.

THE SCREEN ONLY. Signal publishes no headless client and no API. signal-cli is third-party, and a second
unofficial client on the owner's number risks the account, as Baileys does on WhatsApp. So there is no CLI
to read or send messages, and no `chat.v1`: app.json's `wraps.headless` says `none`, which G108 reads as
no API and no flow owed. An agent does not act in Signal.

## What you can do from here

```bash
./bbox signal status [--json]     # the screen is up, Signal runs under it, and when its build expires
```

`status` asks the image's own `signal-health` (desktop/health), which is also the container's healthcheck,
so the console's «ready» says the same. The front door admits only the edge and the console, so a probe by
URL from anywhere else would read its 403 as «down».

## Rules

- Linking is the owner's: he scans the QR the screen shows, with his phone. Never unlink the device.
- Never read Signal's files or its database from outside the client.

## Traps

- Signal refuses to run past the deadline it compiles into each release (its release commit + 90 days),
  while its process stays up. The image is the version: the build reads that deadline out of the package,
  and `status` and the healthcheck fail once it has passed. Rebuild at least monthly, and WITHOUT the cache
  (`./scripts/dc build --no-cache signal-desktop && ./scripts/dc up -d signal-desktop`): a cached rebuild
  keeps the old Signal. Signal moves the deadline 60 days earlier when «download updates automatically» is
  off in its settings, and can set an earlier one itself; those show on its own screen only.
- The keyring holds Signal's database key. A new volume, or a keyring that does not unlock, means linking the
  phone again.
