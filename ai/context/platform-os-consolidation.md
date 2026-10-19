# Platform-OS consolidation — findings, what changed, what is left

One rule drove all of it: **every fact has exactly one owner.** An app's bootstrap belongs to the
app; the desired-state format belongs to the compiler; "how a container is created" belongs to
compose. Where two components implemented the same fact, they had already drifted.

Two adversarial reviews (six subsystem readers, thirty-one skeptics that tried to REFUTE each claim
before it counted) plus direct verification against the live engine. **29 of 30 verified findings
stood; 1 was refuted.** The caps set on those reviews left ~100 claims unverified — listed at the
end, not silently dropped.

---

## The vocabulary, because conflating these caused half the confusion

| Term | What it is |
|---|---|
| `docker` | The **CLI**. Does no work: dials a socket, asks an engine. |
| `dockerd` | The **engine**. Owns the images, containers and volumes. |
| socket | An **address** the CLI dials. |
| the project engine | The `dockerd` inside the WSL distro `Ubuntu`. The only engine this stack uses. |
| Docker Desktop | A *different* engine, own distro, own data. **Never used.** |

---

## What was wrong, and what now owns it

### 1. Desired state had four writers and no schema

`platform.state.yaml` — the file the whole platform compiles from — was written by four independent
regex implementations (`bbox`, `app-management._set_disposition`, `appinstall.state_upsert`,
`packaging/qa-fix-loop.sh`) in **two incompatible shapes**, against one shared reader. Only that
shared reader (`reconcile.disposition()`, which parses both shapes) kept it from breaking. Each copy
carried its own bugs: bbox had already fixed one locally — the old pattern matched only
`{ enabled: bool }`, so enabling an **archived** app reported success and changed nothing — while
`qa-fix-loop.sh` still asserted that limitation as current.

→ **`reconcile.set_disposition()` owns it**, beside the reader, with a `set-state` CLI verb for shell
callers. Text surgery is kept (the file is ~80% comments a YAML round-trip would delete) — it just
lives in one function.

### 2. "Create a container" had two implementations

app-management re-derived compose semantics in docker-py: container_name, image, environment,
volumes, labels, ports, command, entrypoint, user, cap_add. Necessarily a **subset** — a field it did
not translate was dropped *silently*. Its own comment recorded the cost: dropping `command:` cost
portainer its `--admin-password-file`, so a gallery-installed portainer booted into the
**unauthenticated** setup wizard.

→ **compose owns it**, via `scripts/dc` — the invocation `appinstall.start_services()` already used
and documented as "the same one `bbox run` uses". This also brought the control plane under gate G7.

### 3. Apps' bootstraps lived in the CLI

`ensure_portainer_password` (a gallery app that ships **disabled**, minted every run),
`ensure_acme_perms` (traefik's), `ccr_warn_browser42` (in the library every entry point sources).
Wrong on layering — and wrong operationally, because **installing from the apps screen never runs
bbox**, so none of them fired on that path.

→ **each app owns its own**, at `<root>/<id>/hooks/prepare`, invoked generically by
`run_app_hooks prepare` over `reconcile.py enabled-apps`. bbox names no app.

The platform had already diagnosed half of this: `connections/providers/10-infra.yaml` records
`portainer-admin` being pulled out of the layer-1 catalog as *"a base app naming an installable one
… the last item of gate G9"*. The declaration moved; the materialisation had been left behind.

### 4. Nothing converged desired state to actual

Every mutation hung off an HTTP POST, so `_blueprint_apply` fired on enable/disable and never again.
`bbox reset` wipes volumes while state still says `enabled` → n8n comes back **empty**, every app
reads installed, nothing notices. `bbox status` printed "blueprint clean" throughout, because that
check compares git to the working tree and **never asks the instance**.

→ **`reconcile_once()` / `POST /api/reconcile`** converges every enabled app, using a check that can
actually be wrong: `n8n/hooks/present --app <id>`. It distinguishes present / missing / **cannot
tell** — conflating the last two would make a half-started n8n trigger an import. Additive only: it
never deletes.

### 5. Docker Desktop still owned the toolchain

`/usr/local/lib/docker/cli-plugins/` is **entirely symlinks into `/mnt/wsl/docker-desktop/`**,
including `docker-compose`, and that directory outranks the distro's. Every `bbox run` was executing
Desktop's compose (`v2.34.0-desktop.1`) while the package this project installs sat unused at
`v5.3.1`. The engine was independent; the **toolchain was not**.

→ `BBOX_COMPOSE` names the project's own plugin by path. No fallback chain, no machine tweak —
Desktop's symlinks are untouched and simply not consulted.

---

## Four bugs that only testing found

Each would have shipped on the strength of a plausible plan.

1. **Phantom `/repo`.** Deleting the docker-py interpreter looked like pure duplication removal, but
   `_host_repo()` did something compose *cannot* do from inside a container: translate paths between
   container and daemon views. Docker invented a `/repo` tree on the host and handed portainer a
   **directory** where its password file belonged. → repo is mounted at its host path
   (`BBOX_REPO_HOST`); nothing needs translating.
2. **Forked project.** From inside the container compose derives its project name from the mount
   point, saw **0 of 39** containers, and would have built a parallel `repo_*` project with colliding
   container names. → `COMPOSE_PROJECT_NAME` passed explicitly.
3. **A control plane that lied.** The first `reconcile_once` reported `converged` because it had
   *called* something — it claimed to repair drive's blueprint while the push had failed on a stale
   `/repo` path and imported nothing. → it re-asks the question that found the drift.
4. **`DN` unexported.** The derived container-removal list saw an empty deployment suffix, which
   would have force-removed **every** container instead of the two bare-named ones. → passed
   explicitly; exits rather than guess.

---

## 6. Machine sizing had five owners and no envelope

Added 2026-08-06, after a night in which the WSL distro was torn down **42 times in 24 h** (42
systemd[1] inits vs 16 kernel boots — 26 distro restarts with the kernel surviving, and **zero**
graceful docker stops ever recorded). Every teardown orphaned in-flight n8n executions, which n8n
labels *"Workflow did not finish, possible out-of-memory issue"* — a string that is not evidence of
an OOM and cost the team hours.

**The root defect was selection.** `bbox:202` read

    prof="prod"; [ $n -le 4 ] && prof="vps"; [ $n -le 2 ] && prof="ci-small"

— core count alone. Memory was never consulted **even though every profile has always declared
`host_mem`.** The data was there and the selector never asked. A 6-core / 9.7 GiB WSL2 VM was handed
`prod` (`host_mem: 16G`), so the stack was sized for a machine with 65% more memory than it has.
Declared limits reached **4.46x physical** and two services were uncapped entirely.

| Fact | Owner now | Was also decided by |
|---|---|---|
| which profile this machine gets | `platform/manager/select-profile.py`, from `requires: {cores, mem_gb}` per profile | `bbox:202` (cores only); `packaging/linux/adapt-host.py` (cores only, install-time) |
| concurrency / slot counts | the profile — every value pinned in `perf-profiles.yml` | `apitools/src/utils/autoscale.py` (cgroup-derived) |
| cgroup CPU quota read | `autoscale._cgroup_cpu_quota()` | `apitools/gunicorn.conf.py::_allotted_cpus()` — a byte-for-byte duplicate, same app, two files |
| "is the machine well enough to start work" | `scripts/ops/admission-thresholds.sh` | `ops/prejob_waitfree.sh` (6 GiB) and `machine-health-guard.sh --admit` (1.5 GiB), disagreeing |
| declared-memory budget | gate G30 `scripts/refactor/memory-budget-lint.py` | — |
| **observed peak vs physical** | gate G30b, same file (new) | nothing — this was never measured |

`autoscale.py` is now **fallback only**: `explicit env var > module default`, profile always wins.
It is not deleted, because a container run outside this platform (CI, bare `docker run`) still needs
to size itself. The rule it enforces:

> A container sizing itself from its own cgroup is locally correct and globally wrong. It can see
> only its own limit, not the other 43 containers. That is precisely the mechanism that produced
> 4.46x oversubscription — every service sized itself sensibly and the sum was absurd.

**Still open:** `perf-profile-apply` and `select-profile.py` each hand-roll a YAML parser (deferred
deliberately — consolidating parsers is a separate change from consolidating selection);
`adapt-host.py` is still cores-only on the installer path; and the host **alternates between cgroup
v1 and v2 across distro restarts**, so the same compose file does not constrain the stack
identically from one boot to the next.

---

## The defect class this repo keeps producing: *an operation reports success while doing nothing*

Recorded here because it is now the single most repeated bug shape in this codebase, and every
instance was found by checking output rather than by reading code:

`Try Lock` skip returning `success` · `RELEASE` accepting a bare source name and no-oping · manual
`SCAN` debounce silently no-oping (the sync board's "run now" lied) · `$?` inside `wsl bash -lc`
reporting the relay's status, not the command's · discarded `_notes` rendering 2,435 documents as
`0` · `reconcile_once` reporting `converged` because it had *called* something (§ above) ·
`peak-sampler.sh` writing an **empty file and a success message** because `docker ps` returns
12-char ids while cgroup dirs use 64-char ones — in the very tool being used to size the machine ·
`machine-health-guard --admit` printing **`VERDICT: ADMITTED`** on a run where two of its own
sensors had errored.

**The countermeasure, applied to each of the last two:** a check that cannot read its inputs must
FAIL, not pass. `peak-sampler.sh` refuses to write an empty result over good data; `--admit`
validates every metric parses as a number and refuses otherwise. *Absence of a measurement is not
evidence of a good one* — say NOT VERIFIED and stop.

### 2026-08-06 additions — three more, and one of them is in n8n's own API

**`PATCH /rest/workflows/:id {"active": false}` returns HTTP 200 with a full workflow body and
changes nothing.** Measured against the live instance: `workflow_entity.active` stayed `t`, and the
`webhook_entity` row stayed registered, after a 200 whose own JSON echoed `"active": true`. There is
no `POST /rest/workflows/:id/deactivate` (404 `Cannot POST`). What actually works is the CLI,
`docker exec <n8n> n8n unpublish:workflow --id=<id>` — which then prints *"Changes will not take
effect if n8n is running"*, so the DB and the running process disagree until a restart. **Anyone who
deactivates a workflow by trusting the 200 will believe they did something they did not.** Read
`workflow_entity.active` back from Postgres; `tmp/ld_deactivate.py` does exactly that and reports
FAILED when the DB has not moved.

**`$?` through `wsl bash -lc` is worse than the entry above records — it also loses shell variables.**
`wsl bash -lc 'false; echo $?'` prints `0`, and a `for w in a b; do cmd $w; done` runs `cmd` with an
**empty** argument. Both were hit live on 2026-08-06: five gates were reported PASS off a `$?` that
was structurally incapable of being non-zero, and a deactivation loop silently ran against no
workflow at all. `scripts/refactor/run-gates.py` is the sanctioned way to run gates — it reads
`subprocess.CompletedProcess.returncode` and has a `--self-test` that proves the status is real on
this host. Do not write a second one.

**A gate that catches 1 of 8 offenders reads green.** G44 asked "is there a node that can activate
this?", so seven of the eight active test workflows — all carrying a `webhook` beside their
`manualTrigger` — were structurally invisible to it, and the gate looked like it was doing its job.
Fixed by adding a second, independent check keyed off the `lifecycle:test` tag rather than trigger
shape. *A gate's blind spot is not visible in its output; only in the population it never examined.*

---

## Phases

| Phase | Commit | State |
|---|---|---|
| 0 — delete what nothing reads | `f4c7b735` | done — 21 files; compiled compose byte-identical |
| compose plugin ownership | `0be9cf61` | done — G7 extended to police both invocation forms |
| 1 — one state writer | `22a20a96` | done — 4 → 1 |
| 2 — one container-start path | `52589610` | done — −179 lines, control plane under G7 |
| 3 — app bootstraps into apps | `7602e345` | done — bbox names no app in its bring-up |
| 4 — reconciliation loop | `7b232671` | done — verified by breaking it on purpose |

Each verified against a live estate, not just gates: 39 containers, 0 unhealthy, 82 workflows.

---

## What is still open

**Code**

- `perf-profile` upserts 8 settings keys before supabase has migrated, so on a from-scratch install
  they are silently dropped (`relation "settings" does not exist`). Reproduced twice.
- `bbox:629` hardcodes an INDOX workflow id (`IndoxResetFull01`); `apps/indox/hooks/demo.py:51`
  already owns that constant. Needs an app-side hook to move to.
- `scripts/lib.sh` still holds `CCR_FIRSTPARTY_BUILD` (a hand-kept 13-app list — `scripts/built-images.py`
  can derive it) and `N8N_CONTAINER`/`PG_CONTAINER`.
- `scripts/onboarding` creates `traefik-network` itself rather than calling `ensure_network` — a
  second implementation of one guarantee.
- n8n workers declare `image: binaos/n8n:${N8N_VERSION}` with **no `build:`**, relying on the `n8n`
  service to produce that tag. It works; the ordering is undeclared.

**Gate that does not exist yet**

Gate G9 was extended to scan `bbox` and `lib.sh` — a planted violation was **not caught**, because
its detectors match config files and `x["appid"]` subscripts, neither of which applies to shell. The
extension was reverted rather than ship a gate that cannot see. Catching shell-side app naming needs
a real detector, and until it exists nothing prevents §3 from regressing.

**Unverified review claims (~100)**

Verification was capped at 48 of 108 architecture claims and 44 of 139 leak claims. Unverified
entries that look serious:

- `validate()` checks only two of the schema's enums, so a typo in `routing[].auth` would silently
  produce an **unauthenticated route** with no diagnostic from any gate.
- The credential set is committed twice — the second copy documented as gitignored but actually
  tracked.
- `packaging/make-runtime-compose.py` hardcodes a three-file compose list, duplicating
  `reconcile.compose_files()` — and it is the file the shipped artifact boots from.
