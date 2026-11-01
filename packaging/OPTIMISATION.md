# Runtime & packaging optimisation — the measured study

Companion to [native-plan.md](native-plan.md), which set the architecture (one Linux userland, the
engine as a capability, layers 1–2 native inside the guest). That document was written from a
service inventory. **This one is written from measurements taken on the running stack**, and it
changes several of its numbers and two of its conclusions.

Everything below was measured on 2026-07-29 against the stack the Linux executable installed on the
portable machine: 33 containers, 29 images, all 7 routes answering.

---

## The baseline, measured

| | measured | native-plan.md said |
|---|---|---|
| RAM, whole estate | **4.7 GB** across 33 containers | "~10 GB" |
| image store on disk | **11.05 GB** (3.36 GB reclaimable) | — |
| shipped artifact | **2.10 GB** (Linux `.run`) | "2.2 GB" ✓ |
| built services | **21**, from **18** distinct build contexts | — |

The RAM figure matters because the end-state target in native-plan.md ("~3–4 GB, was ~10") reads as
a 60% cut. Against the real 4.7 GB it is a 25% cut, and the phases have to be justified on that.

**Where the 4.7 GB sits — almost exactly in thirds:**

| layer | RAM | containers |
|---|---|---|
| 1 — chassis | 1.56 GB | 9 |
| 2 — base apps | 1.56 GB | 15 |
| 3 — installed apps | 1.55 GB | 9 |

Layers 1–2 are **66% of the estate**, which is what makes them the right target.

**The five largest consumers, all in layers 1–2:**

| | RAM | containers |
|---|---|---|
| authentik (server, worker, bootstrap, its own postgres) | **1132 MB** | 4 |
| n8n (main, 2 workers, 3 runner sidecars) | 770 MB | 6 |
| glitchtip (web, worker, postgres, valkey) | 325 MB | 4 |
| machine (ours) | 213 MB | 1 |
| traefik | 194 MB | 1 |

authentik alone is **24% of the entire platform's memory**.

---

## Finding 1 — the `sql` capability is declared and then ignored

This is the most important structural finding, and it is not in native-plan.md.

Layer 1 ships a `postgres` app that provides the `sql` capability. Three apps declare they require
it:

```
authentik  (L1)  use: [ sql (requires) ]
n8n        (L2)  use: [ sql (requires), kv (requires), secrets, error-tracking (wants) ]
glitchtip  (L2)  use: [ sql (requires) ]
```

The resolver honours those declarations — it pulls `postgres` into the closure and orders it first.
And then each app connects somewhere else entirely:

```
AUTHENTIK_POSTGRESQL__HOST: authentik-postgres     # not the sql provider
DB_POSTGRESDB_HOST=n8n-postgres                    # not the sql provider
glitchtip                 -> glitchtip-postgres    # not the sql provider
```

**Four Postgres servers across three major versions** — supabase/postgres 15.8 (the actual
provider), postgres:16-alpine ×2, postgres:17 — where the graph says there is one.

The declaration is decorative. Nothing verifies that an app which declares a capability actually
consumes it, so the capability graph — the thing the whole platform is organised around — is
silently wrong about its single most important edge.

**That the pattern works is already proven in-tree by `kv`:** both authentik and n8n set
`REDIS__HOST: redis` / `QUEUE_BULL_REDIS_HOST=redis` and use the layer-1 provider. One Redis, two
consumers, no duplication. `sql` is the outlier, not the norm.

**Cost of the outlier:** 3 extra containers, ~325 MB RAM, 2 extra base images in the payload, three
Postgres major versions to keep patched, and three separate backup/restore stories.

### The fix is a gate, not a cleanup

Consolidating the databases by hand fixes today. It does not stop the next app doing the same thing,
and this repo's whole method is that an invariant nobody checks is an invariant that drifts. So:

**G25 — a declared capability must be consumed.** For every `use[]` entry naming a capability whose
provider declares an `endpoint` (`postgres://supabase-db:5432`, `redis://redis:6379`), the consuming
app's compose must reference that provider's host somewhere in its environment. An app that declares
`sql` and names no host but its own fails the gate with both names printed.

Deliberately a *heuristic on the rendered compose*, not a runtime probe: it runs in the cheap CI lane
with no stack, it is the same shape as G13 and G20, and the failure it prevents is a silent
divergence between the graph and reality — exactly what a compile-time gate is for.

Escape hatch: an app that genuinely needs its own store declares
`use: [{capability: sql, own_instance: true, reason: "..."}]`. The point is not to forbid it — it is
to make it a **decision in the manifest** instead of an accident in a compose file.

---

## Finding 2 — what can genuinely become a native binary

"Native" is worth being strict about. A service qualifies only if upstream ships a **single
self-contained binary** that we can supervise directly. By that test:

| service | native? | today | native | verdict |
|---|---|---|---|---|
| **authentik** | ✗ — Python/Django, no non-Docker install | 1132 MB, 4 containers | — | **replace, don't port** |
| ↳ **Authelia** (replacement) | ✓ one Go binary | — | ~50 MB, 1 process | **the single biggest win in the estate** |
| **traefik** | ✓ one Go binary | 194 MB | ~40 MB | do it — and it is forced anyway (below) |
| **caddy** (indox-demo-docs) | ✓ one Go binary | 56 MB | ~15 MB | trivial |
| **redis** | ✓ apt/binary | 13 MB | ~8 MB | not worth a phase on its own |
| **postgres** | ✓ apt | 111 MB ×4 | 111 MB ×1 | the win is **consolidation**, not native |
| **n8n** | ~ npm global install | 770 MB, 6 containers | ~400 MB, 3 processes | medium — internal task runners kill 3 sidecars |
| **glitchtip** | ✗ Django, Docker-only | 325 MB, 4 containers | — | **demote to gallery** — nothing `requires` it |
| **our 6 Python services** | ✗ | 521 MB, 6 containers | see below | **consolidate processes, not compile** |

**Authelia is the headline.** Replacing authentik converts the estate's largest consumer — 1132 MB
across four containers, including a Postgres nobody asked for — into one Go binary of roughly 50 MB.
That single move is worth more than every other native conversion combined, and it is already
recommended in native-plan.md; this study just quantifies why it should be first rather than third.

**traefik is not optional.** v3.3 hardcodes Docker client API 1.24, and Docker 29 raised the daemon
floor to 1.40, so traefik discovers zero routers while reporting healthy. The artifact pins 28.5.2
to dodge this, but the pin cannot hold forever — every distro moves. Moving to a traefik whose docker
provider negotiates the API version (≥ 3.6.2) is a **prerequisite for the platform's lifespan**, not
a native-binary optimisation, and it should be scheduled as such.

### Our own six services: the honest answer is not "compile them"

app-management, connections, console, notifications, any-concurrency and machine are ~8,200 lines of
Python across six containers using 521 MB. Compiling Python to a binary (Nuitka, PyInstaller) keeps
the interpreter and most of the footprint — it buys startup time and little else.

The real cost is **six interpreters, six framework baselines, six containers** for six small
services, four of which are read-only observability surfaces. The win is process consolidation:

```
KEEP SEPARATE (non-negotiable):
  connections      the credential vault. Its entire security model is "the thing that holds the
                   secret is not the thing that wants it" — identity.py names the caller from
                   OUTSIDE the request, over the docker socket. Merging the vault into a shared
                   process destroys the property the broker exists to provide.
  app-management   the control plane. Mutates state, holds the docker socket, and must be able to
                   restart everything else without restarting itself.

MERGE (all four are read-mostly surfaces over docker/pg/logs):
  console + notifications + machine + any-concurrency
                   -> one ASGI app, four routers, one interpreter
                   521 MB -> ~150 MB, 6 containers -> 3
```

That is a ~370 MB cut with no new language, no rewrite, and no loss of isolation that the platform
actually relies on. A Go/Rust rewrite of these four would save perhaps another 80 MB for several
weeks of work and a second toolchain in the build — **not worth it, and this study recommends
against it.**

---

## Finding 3 — build time, and the reproducibility hole underneath it

### The two duplicate builds cost clarity, not wall time

`n8n`, `n8n-worker-1` and `n8n-worker-2` share an identical `build:` block — same context, same
Dockerfile, same args — and compose builds each separately because none carries a shared `image:`
tag. Same for `browser42-browser` / `browser42-reaper`.

I expected this to be the headline build-time finding. **Measurement says otherwise:** the three
n8n images reference 54 layers of which only 15 are unique, so builds 2 and 3 are pure cache hits
and `docker save` deduplicates them in the payload. The cost is three image tags where one belongs,
three entries in every inventory, and a reader who cannot tell whether the workers differ.

Fix is one line — give the main service `image: binaos/n8n:${N8N_VERSION}` and let the workers
reference it with no `build:` block — but bank it as **clarity, not speed**.

### Where build time actually goes

| layer | size | what |
|---|---|---|
| apitools | **655 MB** | one `pip install` (OCR/CV stack) |
| apitools | 128 MB | `apt-get install` poppler, tesseract + language data |
| n8n | **371 MB** | `npm init` + community-node install, fetched from the network |
| n8n | 62 MB | custom-node `npm install --include=dev && npm run build` |

Four network-fetch layers are essentially the entire cold-build cost. Nothing else exceeds 55 MB.
Any serious build-time work targets these four and nothing else — and the highest-leverage change is
not parallelism but **pinning**, because an unpinned fetch cannot be cached across machines and
cannot be reproduced at all.

### The reproducibility hole

G15 pins every third-party `image:` reference and states its own exemption:

> This gate does NOT apply to first-party images. Those are built from this repo by `bbox run`, so
> their content is pinned by the commit, not by a tag.

**That reasoning has a hole, and the hole is load-bearing** because the artifact gets signed. A
first-party image's content is pinned by the commit only for the layers *this repo writes*. Two
inputs float free:

1. **The base.** Every first-party Dockerfile says `FROM python:3.12-slim` — a mutable tag. Same
   commit, different month, different base.
2. **The dependency set.** `app-management` requires `Flask>=3.0 gunicorn>=21 PyYAML>=6.0
   docker>=7.0` and `notifications` requires `flask>=3.0 gunicorn>=21.2 requests>=2.31
   sentry-sdk>=2.0` — **entirely floating**. `connections`, `console`, `machine` and
   `any-concurrency` pin their direct deps but all float `sentry-sdk>=2.0`, and none pins
   transitives.

So two of the six layer-1/2 services cannot be rebuilt byte-identically from their commit, and the
signature attests to a build nobody can reproduce. **Extend G15 to first-party `FROM` lines and
require a lockfile** (`pip-compile`/`uv` output, or `--require-hashes`). This is the change that
makes "reproducible artifact" true rather than intended.

### The compiler emitted CRLF on Windows — found while implementing phase 0

Rendering twice on the same commit and diffing showed all 26 lines "changed" while every include was
identical. `write_text(..., encoding="utf-8")` uses the **platform** newline, and CLAUDE.md lists
Windows as one of three supported environments. `.generated/` is staged into the shipped artifact by
`stage-control.py`, so a Windows-built artifact and a Linux-built one differ byte-for-byte from
identical source. G1's "rendering is byte-identical" cannot hold across platforms, and the manifest
hash the release signs depends on who built it.

> This finding is one of the reasons **G1 was deleted on 2026-07-30**: "rendering is byte-identical"
> could not hold, and the gate that asserted it ran in no lane. The independent measurement is that
> two renders of the same commit differ by 326 lines across 50 keys, because `scripts/ci-env.sh`
> mints fresh secrets into the render. The CRLF bug above is still fixed and still worth having
> fixed — reproducibility matters for the signed *artifact*. What is gone is the claim that a
> committed golden checks it. See `scripts/refactor/GATES.md`, "Why G1 was deleted".

`appinstall.py` and `signing.py` already passed `newline="
"` — someone had met this before.
`reconcile.py`'s twelve writers had not. Fixed, all routed through one helper.

This belongs in the same bucket as the floating dependencies above: three separate reasons the
artifact is not reproducible, none of them visible without deliberately looking.

### And a base image nobody chose

| base | services |
|---|---|
| `python:3.12-slim` | app-management, connections, console, notifications, drive, my-docs, apitools |
| `python:3.13-slim` | any-concurrency, machine |

Two Python bases for eight first-party Python services. Nothing decided this — `any-concurrency` and
`machine` were written later and picked the then-current tag. It costs a second ~119 MB base layer
set in the payload, a second base to keep patched, and a second set of behaviours to reason about.

**Pin one base, by digest, in one place.** Cheapest item in this document and pure clarity.
Done in phase 0: `any-concurrency` and `machine` moved to `python:3.12-slim`, so all nine
first-party Python images share one base. The digest pin is still outstanding.

The same drift exists in Node — `node:22-slim` and `node:20-alpine` — and should be closed the same
way.

---

## Finding 4 — three Docker clients in one platform

Layers 1–2 talk to the Docker socket three different ways:

| service | client | weight |
|---|---|---|
| app-management, machine | `docker` PyPI SDK | +32 MB in the pip layer; drags requests + urllib3 + websocket-client |
| any-concurrency | `aiodocker` | async, much lighter |
| connections (`identity.py`) | **hand-rolled stdlib** — `http.client` over `AF_UNIX`, ~80 lines | zero dependencies |

`identity.py` did this deliberately, and its reasoning is stronger than "it is smaller":

> GET ONLY. This module never mutates the daemon, and keeping that literally true (rather than
> "we only happen to call GETs") is what lets the README state the blast radius of the socket
> mount precisely.

A read-only, dependency-free Docker client that can be *proven* not to mutate the daemon already
exists in this repo, tested, in production. `machine` is a read-only observability surface and has no
reason to hold a client capable of `POST /containers/create`. **Promote `identity.py`'s client to a
shared module and move `machine` onto it** — smaller image, faster build, and a security property
that becomes checkable rather than assumed. `app-management` genuinely mutates and keeps the SDK.

---

## Finding 5 — a database on the public edge

`apps/n8n/docker-compose.yml` publishes its Postgres through traefik's TCP router:

```
traefik.tcp.routers.n8n-postgres.rule=HostSNI(`${N8N_DB_HOST}`)
```

This puts a database on the same edge as the web routes, reachable by SNI, guarded by whatever
`N8N_DB_HOST` happens to be. It is out of scope for a packaging study and I have not changed it, but
it should be reviewed on its own: if it exists for external tooling, that is a decision worth
recording next to the rule; if it is vestigial, it is a listening database that need not be.

---

## Revised phase order

native-plan.md's phases stand. What the measurements change is **the order and the justification**.

| # | phase | why here | measured win |
|---|---|---|---|
| **0** ✅ | **G25 + one Python base + n8n image tag + the CRLF fix** — *landed* | Gates first: they stop the drift the later phases exist to undo | the graph stops lying; one base; renders identically on every platform |
| **0b** | G15 extended to first-party `FROM` + a dependency lockfile | The remaining half of reproducibility | a signed artifact that can actually be rebuilt |
| **1** | **Postgres consolidation** (4 → 1) | G25 makes it enforceable; no native work needed; pure win | **−3 containers, −325 MB, −2 images** |
| **2** | **authentik → Authelia** | The largest single consumer, and the only true blocker for a native layer 1 | **−1082 MB, −3 containers** |
| **3** | **traefik ≥ 3.6.2** | Not an optimisation — the Docker-29 pin is a countdown | unblocks the platform's future |
| **4** | **glitchtip → gallery** | Nothing `requires` error-tracking; `wants` only | −325 MB, −4 containers from default |
| **5** | **Merge the four read-only Python services** | Only worth doing after 1–4 stop moving the targets | −370 MB, −3 containers |
| **6** | **Native conversion inside the guest** (traefik, redis, postgres, n8n, ours) | native-plan.md phases D/E, unchanged | the remainder |

**Phases 0–4 need no native work at all** and take the estate from 4.7 GB / 33 containers to roughly
**3.0 GB / 23 containers**, while making the build reproducible. That is most of native-plan.md's
end-state target, reached without the guest-rootfs rewrite — which is the strongest argument for
doing them first.

## What this study recommends against

- **Rewriting our Python services in Go or Rust.** ~80 MB beyond what process consolidation already
  gives, for weeks of work and a second toolchain in the build.
- **Compiling Python to binaries.** Keeps the interpreter; buys startup time we are not short of.
- **Treating the n8n triple build as a build-time problem.** Measured: the layers dedup. Fix it for
  clarity and stop there.
- **Merging `connections` into anything.** Its isolation *is* the security control.
