# Release readiness — `platform-os-indox-final`

**Host:** portable-ubuntu (192.168.16.103), 4 cores, 15 GB RAM, the machine's own Docker 29.1.3
**Clone:** `~/hacohen-indox-final`, cold volumes, 14 first-party images built
**Updated:** 2026-08-21 · **Status:** IN PROGRESS

This file is the index. Each finding has its own issue; the systemic one is
[`workflow-ts-migration-left-readers-behind.yaml`](workflow-ts-migration-left-readers-behind.yaml).

---

## 1. Verdict

**Nothing found so far contradicts the branch's own correctness.** Every defect is in the
platform's *deployment path*, its *gate machinery*, or its *host prerequisites*.

But that is the release-blocking part, and it is not small: on a clean machine, **`bbox run`
failed, `bbox n8n push all` failed, and `bbox indox test` refused to start** — three of the
handful of commands the docs name as the way to operate this system. None of those failures
were caused by the INDOX changes on this branch.

The dominant cause is one event. Commit `52b32aa4` moved 96 blueprints from `.json` to
`.workflow.ts` and **eight consumers were never repointed**. They were found one failure at a
time; four are now fixed, five remain.

---

## 2. Lane results

| Lane | Result |
|---|---|
| INDOX Python contract suite | **146 passed** |
| Offline flow-QA — desktop | **135/135, 0 JS errors** |
| Offline flow-QA — mobile | **135/135, 0 JS errors** |
| Sim build + audit | **PASS** — 10/10 apps embedded, zero placeholders |
| traefik routing, end-to-end | **PASS** — 302 / 200 / 404 negative control |
| First-party image builds | **14/14 `rc=0`** |
| `scripts/ci/gates.sh` | **32 / 44**, 12 red |
| gate self-tests | **21 / 21** |
| Lean INDOX lane (CI's own derivation) | **20/20 services up** |
| `bbox n8n push all` | **rc=0** *(after fix; was failing on every invocation)* |
| `bbox seed` | **rc=0** — schema + settings applied |
| `bbox indox test all` | **blocked** — G64 needs a `.workflow.ts` reader |
| `bbox run` (full estate) | **rc=1** — authentik bootstrap |
| `bbox ui-map` ×3, `bbox baseline`, CI lanes | pending |

---

## 3. Every change made — complete list

**Twelve commits.** `b01579ac` is the pre-existing session work; the other eleven are this pass.

### Platform / deploy path (behaviour changes)

| Commit | Change |
|---|---|
| `ecc5052a` | `bbox_engine_chosen()` — one engine decision for CLI **and** containers, so `BBOX_DOCKER_SOCK` can never disagree with `DOCKER_HOST` |
| `ecc5052a` | `bbox_assert_engine_socket()` in `dcx` — a missing socket dies naming the path instead of becoming a directory |
| `ecc5052a` | `compose_args()` honours `OVERLAYS` — one `-f` list for both compose entry points |
| `ecc5052a` | **16 hook exec bits restored** — every `backup`/`restore` hook was `100644`, and `run_app_hooks` skips those silently |
| `ecc5052a` | `layer0-lint` (G31) uses the shebang as its discriminator, so a shared module isn't marked `+x` to satisfy a gate |
| `ecc5052a` | `baseline.sh` P0 **probes the API** (can a v1.24 client list containers) instead of reading a version number |
| `ecc5052a` | `baseline.sh` P0 gains a **container-egress check** |
| `55f8c1e5` | `bbox n8n push all` guard accepts `.workflow.ts` — it demanded the `.json` the migration deleted |
| `9f2dc061` | `processLock01` — one owner, keeping the copy that carries the doc-scoped unlock |
| `e801181d` `28e23fb4` | G64 registry repointed at `.workflow.ts`; allow-list moved to the **live** `indoxApi01`; the `PG Upsert` exemption **removed** (its node exists in no live workflow) |
| `717fa2ba` | `sync-engine`'s v3 safety guard reads the `.workflow.ts` — it could only ever refuse |
| `a70677e5` | `flow-qa.py` / `ui-map.py` resolve Chromium instead of hardcoding `/opt/pw-browsers/chromium-1194` |

### Repo hygiene (net removals)

- **Deleted** `apps/indox/grep.exe.stackdump` — a Cygwin crash dump, referenced by nothing; pattern gitignored
- **Deleted** the duplicate `apps/indox/blueprint/n8n/processLock01.workflow.ts` (53 KB)
- **Deleted** the `PG Upsert` allow-list entry — an exemption that outlived its node
- **Deleted** `platform/profiles/build-host-net.yml` — the build workaround, retired rather than left behind
- **Gitignored** the three INDOX cycle CSVs (~68 MB) — evidence, not source
- **Consolidated** two issue files into one; net issue count **61 → 60**

### Findings filed (`issues/`)

`workflow-ts-migration-left-readers-behind` (the systemic one, 8 consumers) ·
`bbox-engine-split-cli-vs-containers` · `ufw-forward-drop-blocks-container-egress` ·
`hooks-committed-non-executable` · `authentik-bootstrap-races-migrations-on-cold-start` ·
`docker29-traefik-warning-does-not-reproduce` · `binaos-docker-bridge-not-persistent` ·
`bbox-run-ignores-overlays` · `gate-failures-20260821-remainder` ·
`hardcoded-chromium-path-breaks-offline-qa` · this report · the consolidation plan

---

## 4. Corrections to standing documentation

**CLAUDE.md's Docker-29 warning does not reproduce on 29.1.3.** Measured through traefik v3.3:
`auth.localhost`→302, `glitchtip.localhost`→200, `bogus.localhost`→404, with
`routerName=authentik-https@docker` in the log. The `bbox baseline` P0 built on that claim was
refusing to run on a daemon that works — **and masked the two faults that were actually breaking
routing on this host.** P0 now asserts the behaviour instead.

---

## 5. Still open

**Needs one root command** — ufw's `DEFAULT_FORWARD_POLICY="DROP"` kills container egress
(`icmp ok`, everything else dropped). Builds are done so it no longer blocks this run, but
runtime egress is dead and **all five CI lanes run on this box**:

```bash
sudo ufw route allow in on docker0 && sudo ufw reload
```

**Needs code** — five gates still `json.loads` a `.workflow.ts`. One shared reader in
`scripts/refactor/` (load `.json`; compile `.workflow.ts` via the existing `wrap.mjs`, cached)
serves all of them. This is what currently blocks `bbox indox test`.

**Needs a decision** — `APITOOLS_CPUS=5.0` in `.env` exceeded the host and `cap-cpus.py`
couldn't see it: the script rewrites `cpus:` literals in compose, not env-driven limits. Capped
to 3.5 locally to proceed.

**Retirement debt** — `indoxApiSupabase01` and `indoxApiRouter01` are both RETIRED and
`active: false`, and both are still called by live blueprints. Not islands, so not simply
deletable — but this is what made the G64 allow-list repoint land on the wrong file first time.
