# Healthy baseline — the one-command fresh proof

The **healthy baseline** is the repeatable, from-scratch proof that the whole platform (המרכז /
digital-office) comes up correctly and every surface works. Run it whenever you want to prove a clean
slate — after a big change, on a new host, or as a nightly regression.

## One command

```bash
./bbox baseline
```

It is deliberately a **fresh hard-reset build run** (never a warm reuse): every run does
`down -v` → `build` (from source) → `up`, so the result reflects the committed tree and nothing stale.
It reuses the existing lane machinery (`ci-env.sh`, `bbox reset/run`, `ci-verify.sh`, `bbox indox test`,
`bbox ui-map`) — `scripts/baseline.sh` only orchestrates and scores. Scorecard →
`ci-artifacts/baseline-summary.md`; exit 0 only if every applicable criterion is green.

## The five criteria (what "healthy" means)

| # | Criterion | How it is proved | Green looks like |
|---|---|---|---|
| 1 | **One command, fresh build** | P0–P3: `ci-env.sh` secretless `.env` → `bbox reset --force` → `docker compose build` → `bbox run --wait` | stack builds from source and every container is Up/healthy |
| 2 | **All tests green** | P4 `scripts/ci-verify.sh` (infra battery) + P5 `bbox indox test all` (functional E2E) | ci-verify all applicable checks pass **and** every INDOX suite green |
| 2c | **Full extraction proof** | P5c `bbox indox extract-gate` — whole Hebrew corpus through apitools OCR + figuring | **`values=527/527`** exact field values (100% accuracy), inside the speed budget |
| 3 | **any-concurrency (כל מקביל) logs** | P6: `GET /healthz` + `/api/sources` + log scan | 6/6 span sources `true`; no `error / retry in / not found` lines |
| 4 | **Notification service (התראות) working** | P7: `GET /healthz` + log scan | `token+poller+db = true`; no `TOKEN not set` / `poll_glitchtip failed` |
| 5 | **Full ui-map verified** | P8: `bbox ui-map` → the one big montage image + two coverage numbers | big image composed; 0 first-party view failures; region coverage ≥ baseline |

## How to read each result

- **P3 bring-up** lists any container that is not `Up`/`Exited(0)`. GlitchTip is provisioned during
  `bbox run` (`ensure_glitchtip_provisioned` → `scripts/glitchtip-push`), which mints the DSNs **and**
  the `notifications` poller token into `.env` — P3 asserts `GLITCHTIP_API_TOKEN` is present, because a
  blank token is exactly the "decorative GlitchTip / dead alert path" failure (התראות shows 0 while
  errors pile up).
- **P4 ci-verify** publishes `ci-artifacts/ci-summary.md` (the named `health-*` / `integration-*`
  scorecard). On a trimmed host browser42 is absent, so its 3 checks are N/A — the script treats only
  browser42 failures as expected and still fails on any real regression.
- **P5 INDOX** writes `ci-artifacts/baseline-indox.junit.xml`. The suites are fully local (Tesseract OCR,
  `DRIVE_BACKEND=local`, GreenMail) — no Google needed. If a suite dies at a Drive/list node with
  *"connection cannot be established … incorrect host"*, the backend routing on `traefik-network` is
  wrong: confirm `INCOMING_DOCS_SUPABASE_URL=http://supabase-kong:8000` and `APITOOLS_DB_HOST=supabase-db`
  in `.env` (baseline.sh sets both).
- **P5c extraction gate** (`bbox indox extract-gate` → `scripts/extract-gate.sh` → `extraction-corpus-check.py`)
  is self-contained: it starts ONE cold apitools container on `:8080` and runs the whole 138-doc Hebrew corpus
  (`production/n8n/demo-docs/`) through OCR + `q_v3_*` field figuring, scoring every value against
  `corrected_truth.json` via the product's own BFF module. Green = `docs=138/138 values=527/527 … gate PASSED`.
  No n8n / db / Gemini / keys. ~3 min here / ~9.5 min on the 6-core reference; budget 4800 s. Log:
  `ci-artifacts/extract-gate.log`. Skip in the baseline with `BASELINE_NO_EXTRACT=1`. Same lock CI runs
  as `local-hebrew-doc-ex`. **Constrained/cgroup sandboxes only** (e.g. dockerd warns "No cpuset support"):
  if apitools freezes mid-OCR (Tesseract's OpenMP can deadlock across concurrent OCR slots there), export
  `OMP_THREAD_LIMIT=1` to serialise each Tesseract call. Off by default — a normal host needs nothing and
  keeps full Tesseract threading.
- **P6/P7** hit each service's own `localhost` `/healthz` **inside the container** (bypassing Traefik +
  Authentik). `/healthz` is red whenever the service can't do its job, not just when the process is down.
- **P8 ui-map** — the big image is `ci-artifacts/ui-map/ui-map.png` (published to `.ci-cd/ui-map/`), with
  per-view PNGs under `ci-artifacts/screenshots-ui/` and the two coverage numbers in
  `ci-artifacts/ui-coverage.md`. Deep-review the montage: a red/amber tile is a failed/skipped view; a
  tile showing a login wall or empty table means that view's backend wasn't reachable at capture time.

## Baseline numbers to beat (last known-good)

- ci-verify: **25/25** on a full host (**~22/22** when browser42 is excluded on a small host).
- INDOX: **all 7 suites** green (`sync_kernel, sync_sources, sync_full, doc_base, bs, gdoc, pipeline`).
- Extraction gate: **`527/527`** exact field values across 138 docs (`bbox indox extract-gate`).
- ui-map: **visible-region coverage 82.1%** (174/212 regions); **76/78 declared views** captured;
  view-code JS ~31.9%. Region coverage should not regress.

## Environment caveats

- **Small-disk / cloud hosts (≤ ~30 GB):** browser42 is dropped (`COMPOSE_PROFILES=`) — its patched-Chromium
  image is huge and pulls from a non-docker.io base. Its 3 ci-verify checks become N/A. Pass
  `BASELINE_WITH_BROWSER42=1` on a big host for a true 25/25. Prune build cache between phases (baseline.sh
  does `docker builder prune -f` after building).
- **TLS-terminating egress proxy (Claude Code web / cloud sandboxes):** `pip`/`npm` inside `docker build`
  fail cert-verify because the build container doesn't trust the proxy CA. The fix — **CA-shadowing every
  base image** with a CA-injected variant (no product Dockerfile edited) — now lives in `scripts/lib.sh`
  (`ccr_shadow_bases`) and is applied automatically by **`bbox run`, `bbox ui-map`, and `bbox baseline`**,
  so a standalone `bbox run`/`bbox ui-map` on a proxied host works without `bbox baseline`. Detected via a
  CA bundle at `PROXY_CA`/`BASELINE_PROXY_CA` (default `/root/.ccr/ca-bundle.crt`). No-op on a normal host.
- **Low ulimit hard cap (cloud sandbox):** `n8n-postgres` requests `nofile` hard 262144; if the host hard
  limit is lower, docker refuses to start it and aborts the whole `up`. `bbox run`/`baseline` call
  `ccr_clamp_nofile` (scripts/lib.sh) to cap `PG_NOFILE_HARD` to the kernel's limit. No-op when the host
  already allows the request (normal laptop/VPS).
- **Concurrent-npm OOM (small hosts):** a parallel `docker compose build` runs many `npm install` at once
  and OOM-crashes npm ("Exit handler never called"), caching a broken layer. On a proxied host `bbox`/
  `baseline` build the first-party images **serially** (`ccr_build_serial`) to bound peak memory. No-op off-cloud.
- **Small writable-disk allowance (cloud sandbox):** un-pruned build cache from ~13 serial builds otherwise
  fills the allowance to 100% ("No space left on device"). `ccr_build_serial` prunes build cache between
  builds whenever free disk dips below `CCR_DISK_MIN_GB` (default 6). No-op where disk is ample.
- **Blocked container registries (network policy):** a Claude-Code-on-the-web environment's egress is the
  **network policy picked at creation**. `bbox run` builds from source, so the policy must allow image
  registries / layer CDNs (Docker Hub + GHCR). If they're blocked, `bbox run` stops fast with a hint to
  recreate the environment with a registry-allowing policy — bbox cannot pull through a blocked CDN.
- **New Docker daemon (29.x+):** Traefik v3.3's docker client speaks API 1.24, but Docker 29 rejects clients
  below API 1.40 — traefik then discovers **zero routers** and every `*.localhost` host 404s (breaks the
  n8n active-state + webhook checks and the whole UI). Start the daemon with **`DOCKER_MIN_API_VERSION=1.24`**
  (`DOCKER_MIN_API_VERSION=1.24 dockerd`) so it accepts the old client. baseline.sh P0 detects a too-high
  daemon min-API and prints this hint; it can't restart an already-running daemon itself. **In the
  cloud sandbox `bbox`'s `need_docker` starts `dockerd` with this flag automatically** (there's no
  daemon at boot), so any `bbox` command already has a Traefik-compatible daemon.
- **WhatsApp** will not pair without a residential/VPS IP (anti-abuse blocks datacenter IPs) — the bot still
  boots; only live pairing is unavailable. This does not affect any baseline criterion.
- **External integrations** (Google/Gemini) stay unconfigured in the secretless `.env`; the stack is healthy
  without them. Only those specific integrations are disabled, not boot.

## Env knobs (scripts/baseline.sh)

Baseline never touches `.env` — it uses yours as-is, so credentials are stable across runs.

`BASELINE_SKIP_BUILD=1` · `BASELINE_SKIP_RESET=1` ·
`BASELINE_NO_INDOX=1` · `BASELINE_NO_UIMAP=1` · `BASELINE_WITH_BROWSER42=1` · `BASELINE_SERVICES="…"` ·
`BASELINE_PROXY_CA=<path>`.
