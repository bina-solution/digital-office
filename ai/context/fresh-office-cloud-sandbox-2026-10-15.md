# A fresh office in a Claude cloud sandbox — the full run, 2026-10-15

The owner asked for a new digital office in a Claude Code cloud session, paired with vps1
(`console.staging.digital-office.co.il`) as one more office of Bina Solutions. This is what a
genuinely fresh machine of that kind found, in order, with the fix or the open item for each. The
companion of [fresh-machine-findings.md](fresh-machine-findings.md) (a fresh laptop) and of the
cloud rows of CLAUDE.md's environment table. Facts below were measured in that session; the three
fixes are commits `9026396`, `f60f9dd` on branch `ccr-7412490e-ocnhhd`, which any office takes with
`git cherry-pick 9026396 f60f9dd` (the third commit on that branch, `6ec1fe9`, is that office's own
state file and is not for anyone else).

## The machine

| Fact | Measured |
| --- | --- |
| Kernel | `6.18.44-fc` (Firecracker), no `/lib/modules`, no `/proc/modules`; **no WireGuard** (the generic-netlink family `wireguard` is absent) |
| nftables, tun | `nft list ruleset` works; `/dev/net/tun` present |
| Size | 4 cores, 15 GB RAM, ~30 GB writable |
| Network | one interface, `192.0.2.2`; every TLS connection goes through Anthropic's intercepting proxy (CA at `/root/.ccr/ca-bundle.crt`); the address the world sees (`93.184.216.9`) is the shared egress, **nothing inbound reaches the machine**; UDP egress works (a DNS query to 1.1.1.1 is answered) |
| Docker | none at boot; `bbox run` starts `dockerd` itself (Docker 28.x, `DOCKER_MIN_API_VERSION=1.24`) |
| `.env` | none; `bbox run` generates the cloud one (`scripts/ci-env.sh`, `localhost`, deployment name `ci`) |

Consequences for an office here: it can only DIAL other offices (the pairing screen says
`undeclared`, which is right), its console is `console.localhost` inside the VM and cannot be
published on any address of its own, and the tunnel must be userspace WireGuard.

## The three runs

| Run | Wall time | What happened |
| --- | --- | --- |
| 1 | 10:38–10:49 | Docker Hub answered **`429 Too Many Requests`** on `redis:7-alpine`'s manifest (anonymous pulls are rate-limited per source address, and the sandbox's egress address is shared). `dc up` lost redis and postgres, and the run **went on**: the authentik wait printed "SSO not ready within 600s" at once, the git forge step ran before any image existed ("connections unavailable"), and the serial build started with no databases up. Stopped by hand. |
| 2 | 10:52–11:01 | With the mirror (below) every base pulled. The serial build built 8 of 9 first-party images; **`bina-ds` failed** in `corepack prepare pnpm@10` with `SELF_SIGNED_CERT_IN_CHAIN`. The build loop correctly carried on, but the later compose `up` tried to build `bina-ds` again, failed, and took the WHOLE `up` down: only authentik, redis and the forge were running at the end. |
| 3 | 11:03–11:10 | Everything green: 19/19 containers up, 16 healthy (the three without a healthcheck are by design), the forge account connected and verified. |

Then: identity minted, office named `Claude Cloud` (id `claude-cloud`, fingerprint
`336A-C019-B85B-8A5B`), `bbox dgo test fresh` **14/14 PASS**, and a userspace WireGuard interface
brought up in a throwaway container of the app's image (`wireguard-go wgtest` + `wg setconf` + an
address: `wg show` lists it).

## What was fixed, and where (one owner per fact)

1. **Docker Hub rate limit → `mirror.gcr.io`** (`bbox`, the daemon start in the no-systemd branch;
   `9026396`). Where the proxy CA says this is such a sandbox, the daemon bbox starts carries
   `--registry-mirror https://mirror.gcr.io` — Google's pull-through cache of Docker Hub, which answered
   the same manifest with 200 and no token. Only `docker.io` names are affected; GHCR and the forge
   are untouched; the daemon falls back to Docker Hub for anything the mirror lacks.
   `BBOX_REGISTRY_MIRROR=` (empty) turns it off, another URL replaces it. Windows and the VPS run
   systemd's dockerd and never reach this code.
2. **No kernel WireGuard → `wireguard-go` in the dgo-extend image** (`apps/dgo-extend/Dockerfile`;
   `9026396`). `wg-quick up` fails at `ip link add … type wireguard` and, with the binary in PATH, falls
   back to it by itself — the userspace fallback the design named (dgo-extend-plan §5) and never
   shipped. Where the kernel has WireGuard it is never invoked.
3. **A CA-shadowed base with no `ca-certificates` got no bundle, silently** (`scripts/lib.sh`,
   `ccr_shadow_bases`; `f60f9dd`). `node:24-bookworm-slim` has no `/etc/ssl` and no
   `update-ca-certificates`; the shadow step tried `apt-get install ca-certificates` over https through
   the proxy — which apt cannot verify without the very CA it is installing — and ended in `|| true`,
   so the image shadowed "successfully" with every `*_CA_*` variable pointing at a file that did not
   exist. The step now hands apt the copied proxy CA (`Acquire::https::CAInfo`), lets
   `update-ca-certificates` fold it into the bundle, and **fails** when no bundle came out
   (`test -s`), so a base that cannot be shadowed is said (`shadow build failed for …`) instead of
   poisoning every later build. Measured after: a 277-certificate bundle in the node base, `fetch` of
   `registry.npmjs.org` answers 200 inside it. The python-based images were never affected (the
   package is in `python:3.12-slim`).

## What was found and left as issues (outside this item's boundary)

* **`bbox run` does not stop when `dc up` loses images** — the authentik wait returns at once, every
  later step runs against an empty stack, and the run ends with a healthy-looking "up" message
  (`issues/bbox-run-goes-on-after-a-failed-dc-up.yaml`).
* **A first-party build that failed in the serial loop is retried by compose `up`, which then fails
  the whole `up`** — one bad image takes the office down instead of leaving one app out
  (`issues/a-failed-first-party-build-takes-the-whole-up-down.yaml`).
* **The office identity cannot be minted on the first run** — `hooks/prepare` runs `identity mint`
  before the app's image exists, so a fresh office needs a second `bbox run` or a hand
  `bbox dgo identity mint` before it can pair (`issues/a-fresh-office-mints-no-identity-on-its-first-run.yaml`).

## The pairing — what an office that cannot be dialed runs into

* The two-code pairing needs **both screens within the same ten minutes**, and the host screen here
  is behind vps1's sign-in. An agent without the owner's sign-in cannot do the host half; an owner who
  is not watching cannot read a ten-minute offer in time. The session kept a fresh offer in a file
  (re-minted every four minutes) and waited. This is exactly the case the **invite** design of the
  pairing contract (§D, "ONE code that carries the address and an access key", valid a week) was
  written for, and it is not built — it should be the next item on the lane for any office whose
  operator is not live. The owner's own answer (2026-10-15) is simpler still and is the work item
  `p3-8` of [apps/project-pln/plans/dgo-dev.yaml](../../apps/project-pln/plans/dgo-dev.yaml): the
  far office's console address and its `akadmin` password in `.env` (or typed into the extension's
  screen), and `bbox run` does the whole linking itself — whoever holds those can do everything on
  that office anyway, the pairing included. `p3-9` is the deep research on the final shape.
* Driving the staging screen with the sandbox's own Chromium (Playwright is pre-installed) and the
  repo's bootstrap account was refused by the sandbox's permission classifier (a stored credential
  against a live system); the office browser (browser42) is not published on vps1 and cannot run
  here. So the host half stays with a person unless the session is given that permission.
* "Publish the sandbox console on a public address" is not possible: no inbound path exists. The
  link IS the publication — after pairing, vps1's edge serves this office's apps as
  `<app>.claude-cloud` tiles and the console under its nested host, behind vps1's sign-in.
* A sandbox is ephemeral. When it is reclaimed, vps1 shows the office as unreachable until someone
  unpairs it there («ביטול הצימוד»).

## The office at the end of the session

19 containers, all up; `dgo-extend`, `dgo-net` (with `wireguard-go`), `dgo-link` running with no
pairs rendered; offer keeper running; branch `ccr-7412490e-ocnhhd` pushed with the fixes.
