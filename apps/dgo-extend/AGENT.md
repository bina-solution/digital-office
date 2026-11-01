# Operating `dgo-extend` — הרחבת הלשכה (`bbox dgo`)

Other digital offices, linked to this one. Two kinds (`GET /api/link` → `items[].kind`):

- **paired** — installed on its own machine and paired from the pairing screen (`/connect`). It runs
  itself: nothing here installs, converges or reaches it. No SSH.
- **office** — a machine in `computers` this office INSTALLS: a declaration (`/data/dgo/<id>.yaml`:
  machine, domain, path, commit, apps) converged over SSH in the fixed steps below.

## The link (both kinds)
One WireGuard pair per linked office. `dgo-net` holds the interfaces (`wg<slot>`), `dgo-link` is the
door — it lives in `dgo-net`'s network, and `scripts/dc` re-creates it with it. Never raw compose.
**Who dials is decided when the pair is written**: a peer's PRIVATE address is dialable only from an
office that declares a private address of its own — a public office listens and the peer dials it.

- **What this office gives**: `serve:` (`POST /api/link/serve`). The door answers only for those apps; a request arrives as the mapped user (`identity.to`).
- **What it shows of others**: every 60 s the app pulls each peer's catalog and declares it as the
  `remote:` block of `platform.state.yaml`; tiles are
  `<alias>.<office>`, a gained or changed app is applied by itself, and a peer that did not answer
  keeps its last catalog marked as not answering. `./bbox dgo project --check` says if it is current.
- **Is it up** — one answer per office, `GET /api/link` → `items[].verdict`: `{ok, hop, why}`.
  `hop` is `tunnel` (no catalog and no handshake — or nothing measured: unmeasured is NOT "alive"),
  `office` (silent behind a MEASURED handshake), `door` (this pair's door is not listening HERE) or
  `pair` (this office dials a private address it is not on: pair again). `tunnel.handshake_age_s`,
  `delivery` and `state_error` sit beside it. The console marks that office's tiles from this verdict.

```bash
./bbox dgo                       # this office and its linked offices
./bbox dgo link status           # per pair: tunnel, handshake, door, catalog
./bbox dgo link up|down <office> # DECLARED offices; a paired one is unpaired on its own screen
./bbox dgo identity fingerprint  # who this office is (stable; in the backup)
./bbox remote <office> <alias> [path]  # that app's doors; with a path, one authenticated call
curl -s http://dgo-extend:8983/api/link | jq '.items[] | {office, kind, state, verdict}'
```

## Moving an app to a linked office
`POST http://app-management:8080/api/apps/<id>/move {"to": "<office>"}` (or the apps screen): the
receiver is asked if it has room, fetches the data over the link and brings the app up; only then is
it switched off here — nothing is deleted. A DECLARED machine moves with
`POST /api/office/<id>/move {"app": …}` (the SSH mover: stop → volumes → start → health → rollback).

## Converging a declared office
```bash
curl -s http://dgo-extend:8983/api/context            # machines, git accounts, domains, this office's commit
curl -s -X POST http://dgo-extend:8983/api/office/<id>/converge -d '{}' -H 'content-type: application/json'
curl -s http://dgo-extend:8983/api/office/<id>/run   # step states + log
```
- **backup** — `pg_dumpall` per postgres, a tar per volume, `.env`, under
  `/root/backup-<ts>-pre-upgrade` (three newest kept); skipped with no room.
- **code** — `checkout --detach <commit>` in `path`; hand edits go to `git stash`, never lost.
- **engine** — pins Docker **28.5.2**. Docker 29 breaks traefik silently.
- **env** — an existing `.env` is only EXTENDED; its secrets are never regenerated.
- **state** — the declaration is the WHOLE app set of that office: anything it does not name is
  switched off.
- **run** — `./bbox run`, detached; its log is read for docker-level failures.
- **health** — running vs declared commit, container health, `console.<domain>`; a host that gives no
  answer says which.

## Traps
- **A dead link is one of two facts, and it heals itself in both.** Either this office's own source
  port was blackholed by a home NAT/router — `wg` counts the initiations as sent and the far side
  captures none (measured twice, on 51820 and 51832) — or the peer's ADDRESS moved: a
  pair's endpoint is a fact of the pairing, so a new DHCP lease on the listening office leaves every
  packet going to an address nobody holds (2026-10-07: hp-laptop came back as `192.168.16.100` while
  the record said `192.168.16.102`, and six port rotations changed nothing). A dialed pair that stays
  unreachable therefore gets BOTH repairs, on their own clocks: a fresh source port
  (`/data/listen-ports.json`) and a bounded, nearest-first search of the lost address's own /24,
  accepting nothing but a completed WireGuard handshake (`/data/find-peer.json` says what it adopted).
  The address goes into the record through the link's one writer, and the record follows the address
  the tunnel uses. `POST /api/link/heal` and `/api/link/find {"office": …}` are the
  deliberate forms — and **neither runs for a pair this office cannot dial at all** (a home `/24` it
  is not on is not a network to probe; 2026-10-12: 8½ min, no peer): that verdict is `pair`.
- `./bbox dgo test <n>` (n ≥ 1) runs REAL link verbs on the live office. Read the phase file first.
- A tunnel endpoint written as a NAME is resolved at render time; a name with no DNS record refuses
  the render, with the record to add.
- The commit of a declared office must be **pushed** — its machine fetches it from the repo.
  `/api/context` → `home.pushed`.
- A machine-sized app set is a decision: what runs on a small remote is what its declaration names.
- An app whose image cannot be pulled there stops `bbox run` mid-stack; `run` reports it.
- Deleting a declaration never touches the machine, its files or its volumes.
- `placement:` (an app shown here through a token door) is the retired model. New work uses `serve:` +
  the catalog.
