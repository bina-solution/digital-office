# Cleanup & consolidation plan — `platform-os-indox-final`

**Principle:** the platform must run on **the machine's own Docker engine**, natively, with no
per-host workaround and no second engine. Every workaround used to get this far is listed below
with the code change that retires it.

---

## Part 1 — Make the platform natively use the local engine (code)

These four changes remove every workaround currently in play.

### P1 — `bbox_select_engine()` must hand containers the engine it chose
`scripts/lib.sh` · retires the `BBOX_DOCKER_SOCK=/var/run/docker.sock` export

`bbox_select_engine()` resolves `DOCKER_HOST` and stops. `BBOX_DOCKER_SOCK` — which compose
interpolates into the socket bind-mount of traefik, machine, connections, app-management and
any-concurrency — keeps its unprovisioned default. The CLI talks to one engine, the containers
are handed another that does not exist.

```bash
export DOCKER_HOST="${ep}" BBOX_ENGINE_RESOLVED=1
case "${ep}" in unix://*) export BBOX_DOCKER_SOCK="${ep#unix://}" ;; esac
```

One decision, one place. After this, a plain `./bbox run` on any host with a working Docker
picks that Docker up for both, which is the whole point of the function.

### P2 — A missing socket must fail loudly, not become a directory
`bbox` / `scripts/lib.sh` · prevents the failure ever being silent again

Docker helpfully creates a bind-mount source that does not exist — as a **directory**. That is
how `/run/bbox-docker.sock` became `drwxr-xr-x` and traefik came up healthy routing nothing.

```bash
[ -S "${BBOX_DOCKER_SOCK}" ] || die "BBOX_DOCKER_SOCK=${BBOX_DOCKER_SOCK} is not a socket"
```

### P3 — `compose_args()` must honour `OVERLAYS`
`scripts/lib.sh` · gives bbox one compose entry point, retires the split

`scripts/dc` reads `OVERLAYS`; `dcx`/`compose_args` — which every bbox verb uses — do not. So
`platform/profiles/ci-images.yml` can never be used with a bbox verb, and any overlay silently
does nothing under `bbox run`.

### P4 — Restore the hook exec bits
16 files · retires nothing, fixes a live data-loss path

`run_app_hooks` skips non-executable hooks **silently**. Every `backup` and `restore` hook in
the platform is committed `100644`, so `bbox export` writes an archive with no databases in it
and reports success.

```bash
git update-index --add --chmod=+x \
  apps/indox/hooks/fixture-sweep.py apps/indox/hooks/sync-registry-converge.py \
  apps/indox/hooks/ui-qa apps/mail/hooks/test.py \
  apps/supabase/hooks/backup apps/supabase/hooks/restore \
  platform-base/{authentik,glitchtip,n8n,postgres,redis}/hooks/{backup,restore}
```

Plus: `run_app_hooks` should *say* when it skips an existing-but-non-executable hook.
(The four `platform-base/data-management/hooks/*.py` run via `python3 <path>`, so the bit is
not load-bearing there — but G31 does not model that, so either set it or teach the gate.)

### P5 — `bbox verify` must test container egress
`scripts/lib.sh` · turns a whole failure class into one line

A container that cannot resolve a name is a host-readiness fact checkable in one second. Not
checking it cost 55 identical DNS failures presenting as a flaky network.

```bash
docker run --rm alpine:latest nslookup pypi.org >/dev/null 2>&1 \
  || warn "containers cannot resolve DNS — if ufw is enabled: sudo ufw route allow in on docker0"
```

---

## Part 2 — The one host prerequisite (needs root, once)

ufw is enabled with `DEFAULT_FORWARD_POLICY="DROP"`. Container egress is dead: `icmp ok`,
everything else dropped. This is **host firewall config, not something the platform can or
should work around** — no amount of code makes a dropped packet arrive.

```bash
sudo ufw route allow in on docker0 && sudo ufw reload
```

P5 makes the platform *diagnose* it in one line instead of failing 55 times. `bbox install
debian` should also set it, alongside installing Docker.

Once this is done, **delete `platform/profiles/build-host-net.yml`** — the host-network build
overlay exists only because of this and must not outlive it.

---

## Part 3 — Clean the box down to one of everything

| Item | Action |
|---|---|
| `/run/bbox-docker.sock` (stray directory) | `sudo rmdir` — it is the artefact of the P2 bug |
| `platform/profiles/build-host-net.yml` | delete once Part 2 lands |
| Old clones (`platform-os-net`, `binaos-repo`, runner workspace) | **leave alone** (per instruction) |
| Running containers | exactly one stack, from `~/hacohen-indox-final` |
| Actions runner | **untouched**, left running |
| `binaos-docker.service` | leave failed — we are using the local engine natively now. Its bridge bug is filed; not needed for this. |
| Disk | 20 GB free and falling. Prune build cache between lanes; `bbox baseline` needs headroom. |
| `DEPLOYMENT_NAME` | currently `posnet`, inherited from the copied `.env`. Rename to `indoxfinal` for a clean, self-describing deployment — **this creates fresh volumes**, i.e. a genuinely cold run (right for release verification, slower: full re-OCR). |

---

## Part 4 — Branch consolidation

- Three run-output CSVs (~68 MB) are still untracked: `completed-docs`, `completed-merged`,
  `decide-census`. Decision needed: `.gitignore` them (recommended — they are evidence, not
  source) or commit them.
- `legacy/indox-retired-20260821/` and `legacy/indox-routing-proofs-20260821/` are committed and
  referenced from the commit message; `attic/` is covered by G34, which is currently green.
- Keep history as-is — the findings commits are the audit trail.

---

## Part 5 — Testing & verification checklist

Run **in this order**; each line is a pass/fail with recorded evidence.

### Static — no stack required
- [x] `scripts/ci/gates.sh` — 44 gates · **32/44**, 12 red (all filed)
- [x] `gates.sh --verify-ci` — registry drift · **RED**, filed
- [x] gate self-tests — **21/21**
- [ ] re-run gates after P1–P4 land; target is a *known* red set, not a shrinking mystery
- [x] INDOX Python contract suite — **146 passed**
- [x] `node digital-office/sim/build.mjs` — **PASS**
- [x] `node digital-office/sim/verify-sim.mjs` — **10/10 embedded, no placeholders**
- [~] `flow-qa.py` (desktop) — running
- [ ] `flow-qa.py --mobile`
- [ ] `digital-office/sim/ui-map.py --all` (3 profiles, offline)

### Bring-up — natively, no workaround
- [ ] `./bbox run` **with no env overrides** — the real acceptance test for P1/P2
- [ ] `./bbox status` — every container healthy
- [ ] `./bbox verify` — host + stack + n8n creds/keys
- [ ] traefik: >0 routers, and a known Host routes (302/200) with a 404 negative control
- [ ] container egress: DNS resolves from a bridge container

### Functional
- [ ] `./bbox indox test` — the E2E suites (**the headline deliverable**)
- [ ] `./bbox test apitools` — feature-validation / OCR suites
- [ ] `./bbox onboarding`
- [ ] `./bbox seed` then spot-check the UIs render real content

### Visual
- [ ] `./bbox ui-map` — desktop
- [ ] `./bbox ui-map --profile mobile` / `--profile tablet`
- [ ] `scripts/ui-coverage/sim-live-parity.py` — sim vs live

### Whole-system
- [ ] `./bbox baseline` — reset→build→up→ci-verify→indox test→ui-map→scorecard.
      Note its P0 currently refuses Docker 29; see
      `docker29-traefik-warning-does-not-reproduce.yaml` — that gate needs to assert behaviour,
      not a version number, or baseline cannot run here at all.

### CI (after Part 2)
- [ ] `indox-e2e` · `ci-verify` · `ui-map` · `local-hebrew-doc-ex` · `release-bundle`
- [ ] all five are `runs-on: [self-hosted, portable]` — **never concurrent with a manual stack**;
      `indox-e2e` opens with `docker rm -f $(docker ps -aq)` + `docker volume prune -af`
- [ ] none auto-run on this branch — the push filters name
      `[main, shlomo-laptop, release-v2-lockin, platform-os-refactor]`. Add this branch, or
      dispatch manually.

---

## Sequencing

1. Land P1–P4 (code) — small, independent, each with its own commit
2. Part 2 (one root command) → delete the build overlay
3. `./bbox run` clean, no env overrides ← proves P1/P2
4. Functional + visual lanes
5. `bbox baseline`
6. CI, one lane at a time, stack down
