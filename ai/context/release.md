# Release Runbook

Minimal spec for releasing the deployment. Working branch = deployment main dir name (`deployment-hacohen`); release target = `main`.

## Steps

0. **Branch alignment** — verify the repo is on the `deployment-hacohen` branch; if elsewhere, move with all changes. Back up the prior branch (keep `old branch locally). (`apitools` + `chat` are in-tree — one repo, no submodules to align.)
1. **Full code review** → write report to `data/reports/before-release-report.md` (sections below).
2. **Version bump** — homepage `+0.0.1` in `production/homepage/config/settings.yaml` (`title:`).
3. **Ask** if ready to commit.
4. **Commit all** — `git add -A && git commit` on `deployment-hacohen`.
5. **Open PR**: `deployment-hacohen → main` (single repo).
6. **Provide PR links.**

## Secret handling (do before commit)

- Save any important keys **not already in `.env`** into `.env` (gitignored).
- Delete secret files from the project **and** GitHub; track rotation in `./issues/<name>.md` (rotation is the real fix — git removal alone doesn't undo exposure).
- Harden `.gitignore` (`.env.*` w/ `!.env.ex`, `data/db-dumps/`, `data/chat.json`, `**/*credentials*.json`, session-exports).
- Keep secrets out of the pushed branch history (squash off `origin/main`; preserve full history on the backup branch).
- Pre-commit gate: `git grep --cached` for secret patterns must be clean.

## Report sections (`before-release-report.md`)

0. **High-End Overview** — executive summary + readiness scorecard + verdict.
1. **Changes Overview** — `main` → release (commits, restructure, new/removed services, risk table).
2. **Security Overview** — secrets handling, auth/authz, network exposure, injection/SSRF, supply chain; severity table + posture.
3. **Code Quality** — readability, error handling, duplication, tests; per-subsystem rating.
4. **Minimality / Repeatability / Proper Structure** — bloat, pins/`:latest`, build determinism, layout.
5. **Declarativity** — compose+`.env` coverage, dynamic discovery, imperative seams.
6. **Configurability** — hardcoded vs dynamic vs integrated vs manual; high-end + per-service rating.
7. **Scalability** — horizontal/vertical, resource limits, bottlenecks/ceilings.
8. **Efficiency** — solution-level runtime (per service) + project/CI-CD/build (build speed, images, `.dockerignore`) + storage/resource.
9. **Deployment / Infra** — compose integrity, volumes, ports, healthchecks/ordering.
10. **Application Code Correctness** — severity-ranked bugs (file:line).
11. **Feature Validation** — **run** the FV suite and summarize pass/fail per feature.
12. **Deployment Context Overview** — verify `ai/context/` docs align with the actual deployment (drift).
13. **Minimum gate to merge** — blocking items.

Each dimension: be concrete (file:line), rate it, list top fixes.
