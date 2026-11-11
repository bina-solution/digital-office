# Operating `office-routes` — ניהול רשת (`apps/office-routes`, DGO-543)

The office's own **routes**: what it answers on, from where, and at which address. One screen, one
declaration, one writer — and nothing open by default.

Vocabulary: a **route** is a way INTO this office. `*.localhost` always exists (the machine resolving
its own names). `lan` is the office's own address on the machine's network — the door a phone walks
through — and it is CLOSED until somebody opens it here.

## What the chain is (and which half you are touching)

    the screen (this app) → the control plane → the compiler → the edge + the machine
    PUT /api/routes/lan     PUT /api/network    network-set    routers · .generated/network.json

- The DECLARATION is `network.routes` in `platform.state.yaml` — the file the console writes, the
  same one `apps:` and `remote:` live in. This app never edits it; it asks the control plane, whose
  compiler verb validates BEFORE writing (a refused block changes nothing, one sentence per reason).
- The COMPILE renders the edge side (`Host(<address>)` twins of the console's whole URL space, the
  sign-in's host and its authentik provider, `AUTH_EXTERNAL_URL`) and the machine side
  (`.generated/network.json`). A route declared but not compiled serves nothing.
- The MACHINE side is `scripts/windows/firewall-converge.ps1`: it reads the compiled facts and opens
  **TCP 80, scoped to the machine's own subnets** — one UAC consent prompt, on the owner's
  `bbox.cmd run`. Nothing this app does can open that door by itself.

## What you can do from here

> **The id is `office-routes`, not `network`, and that is load-bearing twice.** (1) This engine also
> runs a second stack on the same edge network, with a service called `network` of its own: a docker
> name two containers answer to is round-robined between them (measured 2026-10-12 — the console's
> proxy served the OTHER office's app under this tile), and the neighbouring router claims
> `Host(network.localhost)` too. (2) An everyday word as an id fires gate G31 on unrelated code
> (`ensure_network`). Same rule: dial the control plane as `app-management-<DEPLOYMENT_NAME>`, never
> the bare name `.env` carries — `bbox status` lists it as answered by two containers.

```bash
curl -s http://office-routes:8080/api/routes | jq         # the reading the screen draws
curl -s http://office-routes:8080/api/routes | jq .suggested,.own_host   # hint + our own host
# knock ONE address: `answers` (something listens there) and `ours` (it is THIS office's edge)
curl -s -X POST http://office-routes:8080/api/probe -H 'content-type: application/json' \
     -d '{"address":"192.168.16.102"}'
# FIND the machine's own address: nearest-first over that address's own /24, identity-checked,
# bounded (254 knocks, 0.7s each, 12s in all), stops at the first verified answer
curl -s -X POST http://office-routes:8080/api/find -H 'content-type: application/json' \
     -d '{"address":"192.168.16.100"}'                    # -> found: ["192.168.16.102"]
python3 apps/office-routes/tests/routes_acceptance.py           # reads, proves refusals; opens nothing
```

## Traps

- **Opening a route is the OWNER's action, from the screen.** It exposes the office's sign-in page to
  every device on whatever network the machine is on (hotel, café, customer) — the sign-in is the
  gate and the firewall scope is the machine's own subnets, but the decision is his. Never open one
  to "test" it, and never declare one in `.env` (tried and rejected: DGO-542 → DGO-543).
- **A route is `enabled: true` or it is closed.** A route declared without it is a remembered choice,
  not an open door — `network.routes` with an address and no `enabled` renders NOTHING.
- **The address must be this machine's, and three halves check it.** The compiler refuses a malformed
  address in one sentence; the screen refuses one that does not ANSWER *as this office*; and
  `firewall-converge.ps1` — the only half that can see the machine's interfaces — refuses to open its
  TCP 80 rule for an address the machine does not hold (fail closed). A container cannot read them
  at all: its `/proc` is its own network namespace (measured 2026-10-12).
- **"Ours" is one measured signature**: asked on this office's host, the edge answers `302` →
  `auth.<this office's domain>`. A router, a printer, the second stack — none of them sends a caller
  to this office's sign-in. The app is told its host by `OFFICE_ROUTES_BASE_URL` (`sso.base_url_env`);
  without it identity is `null` and NOTHING is refused on it — a check that cannot run must not block.
- **A stale hint is found, not waited for.** The offered address is what the office already declares
  about the machine (`DGO_WG_ENDPOINT`, written by a host-side step) and it CAN be a lease behind —
  measured: the machine held `.102` while `.env` said `.100` for a day. Then «מצא את כתובת המכונה»
  (`POST /api/find`) walks that address's own `/24` from the near side and returns only addresses this
  office answered at. Never run it against a network that is not the office's own.
- **The sign-in moves with the route.** A browser that is not ON the machine cannot reach
  `auth.localhost`, so `AUTH_EXTERNAL_URL` is set to the route's address while it is open — which is
  why closing restores the byte-identical localhost-only render, and why an office on
  `AUTH_PROTOCOL=https` cannot serve this door at all (refused, not half-rendered).
- **`/outpost.goauthentik.io/` is deliberately NOT routed to the identity on that address**: the
  outpost's callback is answered by the console router's forwardAuth middleware, and
  `authentik-server` answers 404 for that prefix — measured 2026-10-12.
- **Closing is exact**: `enabled: false` (or no block) restores the previous render byte for byte and
  the machine's rule is removed on the next `bbox.cmd run`.
