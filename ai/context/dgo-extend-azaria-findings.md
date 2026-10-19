# dgo-extend — three traps measured live on 2026-10-01 (lane: עזריה, DGO-30/32)

Written because two lanes are editing `apps/dgo-extend` at the same time and each of these cost real
time to find. They are properties of the DEPLOYED system, not opinions about the code.

## 1. The peer's rendered firewall must not be applied on a MACHINE

`converge.step_link` ships the PEER's document to the far machine and applies it with `wg-quick` +
`nft -f` there. That document's `forward` chain used to carry `policy drop`. On a machine (rather than
inside the tunnel's own container namespace) that is a base chain at the `filter` priority shadowing
iptables', and **a base chain's accept is not final across chains** — so it silently killed every
published container port on vps1:

* `tcpdump -n -i eth0 'tcp port 443'` showed SYNs from the owner's home IP arriving and **never
  answered**;
* `https://console.staging.digital-office.co.il/` was unreachable from outside, while the box itself
  answered `302` on loopback and every health screen was green;
* the same rule set was applied TWICE on every converge (`nft -f` MERGES): each rule was listed twice.

Fix (commit `c23e1d2d`): `firewall.nft_document(..., forward_policy=…)` — `drop` in the tunnel's own
container, `accept` on a machine (the link's own packets are still dropped by name), and `up.sh`
deletes `table inet dgo` before applying. Applied live on vps1 the same hour: console answered `302`
again.

## 2. `Endpoint` must be an IP — a name breaks inside a container

`wg-quick up` inside `dgo-net` fails with `Name or service not known` on
`Endpoint = staging.digital-office.co.il:51820`: the platform's containers get a resolver that does not
answer for public names. The entrypoint logs `wg-quick failed on re-apply` and **carries on**, so the
office runs with no tunnel while every screen says the link is up. Resolve through `computers`
(`machine_record(...).host`) — that is what `converge._dial_address` already does for the peer's side.

## 3. Render the HOME side, not the declarations

`POST /api/tunnel/render` (and anything that re-renders after a `serve:` change) must write THIS
office's own plan into `/tunnel`. Rendering each declaration instead wrote a PEER's firewall into this
office's tunnel volume — no `accept` for a single served port — so a `serve:` change turned delivery
off on the very office that had just declared it. The pair form (`pair={"slot": <home slot>, "side":
1}`) is needed because the pair shares one /24 and both ends store the same slot.

## What is missing on the receiving side (DGO-32)

`bbox agent` on an office that does not run an agent itself now discovers one from `serve:` in
`platform.state.yaml` and reads the token the serving office handed into its vault
(`dgo_link-serve-<office>-<app>-agent`, written by `converge._handoff_agents` through `computers`).
The tile path needs, in addition: the app's own `Host` (`sso.default_host`) sent by the peer's edge —
the harness refuses any authority it was not told about (measured: nested console host answers
nothing, `bina.localhost` answers 200).
