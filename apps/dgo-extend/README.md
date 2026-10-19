# dgo-extend — הרחבת הלשכה

Other digital offices, linked to this one. An office is one `./bbox run` on one machine; this app
is where a second office is **paired** or **declared**, where the link between two offices is
rendered and kept true, and where the apps the other office gives are turned into tiles here.

Agents operating it read [AGENT.md](AGENT.md) (verbs, endpoints, traps). This file is the map: what
the app is made of, which file owns which fact, and what is no longer true.

## Two kinds of linked office

| | **paired** | **office** (declared) |
|---|---|---|
| What it is | an office installed on its own machine, by its own owner | a machine in `computers` that THIS office installs |
| How it joins | the pairing screen (`/connect`): QR, camera, or the same offer pasted as text; both screens show the same six digits | a declaration (`/data/dgo/<id>.yaml`) converged over SSH |
| Who runs it | itself. Nothing here installs, converges or reaches its machine. **No SSH.** | this office: `machine → dns → backup → code → engine → env → state → run → health → publish` |
| Example | hp-laptop ⇄ MacBook (paired 2026-10-04) | vps1 |

Both kinds get the same link.

## The link, hop by hop

```
 this office                                                   the other office
 ┌──────────────┐   wg<slot> · 10.79.<slot>.0/24 · one /32 per side   ┌──────────────┐
 │ console tile │──▶ door (dgo-link) ══▶ tunnel (dgo-net) ══════════▶ │ door ─▶ app  │
 └──────────────┘                                                     └──────────────┘
```

* **Tunnel** — one WireGuard interface per pair (`wg<slot>`, `10.79.<slot>.0/24`, `.1` and `.2`).
  It routes no subnets: a peer's `AllowedIPs` is its own single address. One side listens (a
  published UDP port, `DGO_WG_PUBLISH_BIND` / `DGO_WG_PUBLISH_PORT` in `.env`, and the machine's own
  firewall must let it in); the other dials and needs no open port. The dialing office tells the
  listening one where it reached it (`dials`, in its catalog answer), so a listener whose lease
  moved shows and offers the address it really has before its next run re-declares it.
* **Permission** — a firewall rendered from the declaration and enforced where the packet ARRIVES.
  A token proves who is calling, not what they may do.
* **Delivery** — the door. It answers only for the apps this office `serve:`s, by host name, and a
  request arrives as the mapped user. A door that cannot deliver answers for itself: a card for a
  page request, a bare status for a call, and `X-Dgo-Door: no-app | app-down | unreachable` either way.
* **What ONE office is given** — `serve:` is the office's one list, and two reserved keys narrow it:
  `exclude` (published to nobody) and `only` (`{"vps1": ["plane"]}`: that office is given exactly
  those; an empty list is "linked, and given nothing"; an office not named is given the list).
  It is enforced on the serving side alone, where the request arrives: each pair's door asks for
  its route table in its own office's name, so a name that office was not given is `no-app` there,
  and the catalog that office pulls lists only its own. The door writes which office is asking
  (`x-dgo-office`) and removes whatever the peer wrote — an office cannot ask for another's list.
  `POST /api/link/serve {"serve": {"*": {}, "only": {…}}}`; re-declaring `serve` without `only`
  keeps the narrowing, `"only": {}` clears it.
* **What is shown** — every 60 s the consuming side pulls each peer's **catalog** (a projection of
  that office's own compiled registry — never a second list) and declares it as the `remote:` block
  of `platform.state.yaml` through the control plane. Tiles are `<alias>.<office>`.
* **Is it up** — one verdict per office, used by every surface: `{ok, hop, why}` with `hop` one of
  `tunnel` (no catalog and no handshake for three minutes), `office` (silent behind a live tunnel),
  `door` (this side's door is not listening). The console marks that office's tiles from it. An
  office that has only just gone silent is asked again every 8 s for five passes, and until they
  are spent it is unmeasured (`ok: null`, «ממתינה לחיבור») — one failed pull is not a verdict.

## Who owns what

| File | Owns |
|---|---|
| `app.py` | the HTTP API and the screens; the verdict (`_verdict`); the published link state (`/data/peers/link.json`) |
| `identity.py` | one Ed25519 key and one WireGuard key per office, in the `dgo_identity` volume (in the backup) |
| `pairing.py`, `pair_api.py` | the pairing offer (public material only — a QR is a photograph), the rendezvous, the six-digit confirmation, the grant |
| `declaration.py` | the rules a declaration must satisfy, as pure functions (slots, sides, ports) |
| `links.py` | the token of ONE direction of ONE link — a row in the credential plane, never in a file |
| `net.py` | what the tunnel must be: interface, addresses, listen port, per pair |
| `firewall.py` | what one link ALLOWS (permission), rendered as nftables rules |
| `linkproxy.py` | the delivery PLAN: which door listens where, for which app (`link-proxy.json`) |
| `link-proxy.py` | the process that APPLIES that plan in the tunnel's network namespace (the `dgo-link` container) |
| `catalog.py` | what an office says about its own apps (serving side), and what a peer accepts it saying (consuming side) |
| `projection.py` | pull each peer's catalog; write `remote:` here through the control plane |
| `converge.py` | the fixed, idempotent steps that install and update a DECLARED office over SSH |
| `move.py` | the SSH mover for a declared machine: stop → volumes → start there → health → rollback |
| `peers.py` | **retired model** — placement (an app that runs there behind a token door). Do not add placements |

`linkproxy.py` and `link-proxy.py` are two halves on purpose: the one that plans has an opinion and
no network; the one that applies has the network and no opinion, so a change of plan is a re-render
and never a new container.

## Containers

| Service | What it is |
|---|---|
| `dgo-extend` | the app: API on 8983, the two screens (`static/index.html`, `static/connect.html`) |
| `dgo-net` | the tunnel: holds the `wg<slot>` interfaces (`NET_ADMIN`, `/dev/net/tun`), publishes the one UDP port of an office that listens |
| `dgo-link` | the door: lives in `dgo-net`'s network (`network_mode: service:dgo-net`) and applies the delivery plan |

All three run the same image. `scripts/dc` re-creates `dgo-link` whenever `dgo-net` is replaced —
a container that lives in another's network follows it. After rebuilding the image, bring the
tunnel's two containers onto it too (`./scripts/dc up -d dgo-net dgo-link`); re-creating `dgo-net`
drops the learned endpoint until the dialing side handshakes again.

Volumes: `dgo_extend_state` (declarations, pulled catalogs), `dgo_extend_peers` (the published link
state), `dgo_identity` (the keys — read-only to the app), `dgo_tunnel` (the rendered tunnel,
firewall and delivery documents).

## Verbs

```bash
./bbox dgo                        # this office and its linked offices
./bbox dgo link status            # per pair: tunnel, handshake, door, catalog
./bbox dgo link up|down <office>  # a DECLARED office only — a paired one is unpaired on its screen
./bbox dgo identity fingerprint   # who this office is
./bbox dgo project [--check]      # pull the catalogs now / say whether the state file is current
./bbox remote <office> <alias> [path]   # that app's doors; with a path, one authenticated call
```

Each verb is a hook under `hooks/` and runs on the machine: `state` (the default), `link`,
`identity`, `project`, `test`; `prepare` and `migrate` run at bring-up (the rename from `offices`).

## Tests

| Run | What it holds |
|---|---|
| `./bbox dgo test 0` | phase 0, and the frame every phase uses (`tests/phase0.py` is the runner: a check returns ok + what was measured, every check runs, the exit code is the answer) |
| `./bbox dgo test 1` | tunnel and link: a stable identity that is in the backup, both ends answer a ping THROUGH the tunnel, a forged source drops, a revoke takes the peer down on both sides, the door says why when it cannot deliver |
| `./bbox dgo test 2` | the portable office: a machine on the LAN becomes a linked office |
| `./bbox dgo test 3` | the reverse direction and pairing: the `serve:` rules and their refusals, and §9's trust boundary (`tests/test_link_security.py`) |
| `./bbox dgo test fresh` | two brand-new offices, as real processes, pair through the real API |
| `python3 apps/dgo-extend/tests/pair_contract.py` | the pairing codes, through BOTH languages (server and screen) |
| `python3 apps/dgo-extend/tests/test_link_security.py` | §9 of the pairing contract, one test per claim — prints `XFAIL` with the code path for a claim the code does not hold |
| `node apps/dgo-extend/tests/connect-selftest.mjs` | the offer format the screen reads and writes (gate G72 runs it) |
| `tests/move_acceptance.py`, `tests/move_back.py` | an app moves to another office WITH its data, and back — on real machines |

`./bbox dgo test <n>` for n ≥ 1 runs REAL link verbs on the live office. Read the phase file first.

**§9's trust boundary has two claims the code does not hold yet** (measured 2026-10-11, DGO-49).
They are tests here, not prose: `tests/test_link_security.py` prints them as `XFAIL` with the code
path named, and every `PASS` line is a claim that does hold.

* `POST /api/apps/<id>/apply` carries no link guard — `platform-base/app-management/app.py:api_apply`
  runs the compile and the recreate for a caller that arrived over a link, while its twin
  `PUT /api/remote` (same file, `api_remote_put`) refuses one with 403. §9 names both routes.
* A `serve:` identity's `from` crosses the link in a shape the far end cannot read: `catalog.build`
  publishes it as a LIST (`catalog.py:161`) while `platform/manager/serve.py:357` reads one header
  string, so `sorted({… 'from'})` raises `TypeError: unhashable type: 'list'` and the consuming office
  cannot compile at all. Nothing validates `from` on the way in (`/api/link/serve` checks `to` alone).

A fix that closes one turns it into `XPASS`, which FAILS until the marker is removed — a gap cannot
be closed quietly, and a marker cannot be left behind.

`AGENT.md` is the brief the compiler injects into every agent session, under a 6000-byte budget
(`reconcile.MAX_BRIEF_BYTES`). This app's is 5978 — 22 bytes of room, so anything added there has to
be paid for by cutting something else, or `reconcile validate` refuses the whole catalog.

## What is no longer true

* **Placement** (`peers.py`, the `placement:` key): an app that ran on a remote office and was shown
  here through a token door. Retired on 2026-10-01 — "apps just run where they run"
  ([dgo-remote-apps.md](../../ai/context/dgo-remote-apps.md)). New work uses `serve:` + the catalog.
* **SSH to hp-laptop** ([SECOND-OFFICE.md](SECOND-OFFICE.md)): that office joined by pairing and
  runs no SSH server, by its owner's ruling. The document stays as the record of the declared route.
* **The state file written through `computers`**: `remote:` is written through the control plane
  (`PUT /api/remote` on app-management); an office with no door to its own machine still projects.

## Further reading

[ai/context/dgo-extend-plan.md](../../ai/context/dgo-extend-plan.md) — the design and its decisions ·
[dgo-pairing-contract.md](../../ai/context/dgo-pairing-contract.md) — what the two sides of a pairing
exchange · [dgo-remote-apps.md](../../ai/context/dgo-remote-apps.md) — the model of an app that runs
elsewhere and the whole data path.
