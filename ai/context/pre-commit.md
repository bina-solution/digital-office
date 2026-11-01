# Pre-Commit Runbook

Minimal spec for reviewing + safely committing the **uncommitted working-tree changes** on the dev branch. Same routine as the release runbook ([release.md](release.md)) but the **baseline is `HEAD`** (latest pushed `shlomo-laptop`), not `main`.

- **Diff scope** = `git diff HEAD` + untracked (`git ls-files --others --exclude-standard`). NOT `main..HEAD` — that's the release runbook's job (run it *after* this, on the committed history). (Everything — including `apitools` + `chat` — is in-tree now, so the parent-repo diff covers it all; no submodule working trees to scan separately.)
- **Endpoint** = a clean commit on `shlomo-laptop` (no PR, no version bump — those belong to the release runbook).
- Working branch = deployment main dir name (here `shlomo-laptop`).

## Steps

0. **Branch alignment** — verify the repo is on `shlomo-laptop`; if elsewhere, move with all changes.
1. **Secret gate** (before commit) — see section below. Scan the **uncommitted** delta + untracked files.
2. **Full code review of the uncommitted delta** → write report to `data/reports/before-commit-report.md` (same sections as the release report, scoped to what's changed vs `HEAD`).
3. **Decide untracked files** — for each untracked path, decide commit vs `.gitignore` (scratch/planning dirs, snapshots, dumps → gitignore; real artifacts → commit). List the decisions.
4. **Apply mandated fixes** — anything the review marks BLOCKER/secret-handling that is cheap + clearly-correct (e.g. env-var doc gaps, doc drift) gets fixed now so it lands in the same commit.
5. **Ask** if ready to commit.
6. **Commit all** — `git add -A && git commit` on `shlomo-laptop` (single in-tree repo — no submodule gitlinks to bump).
7. **Report** the commit SHA(s). Stop here — hand off to [release.md](release.md) for the `→ main` flow.

## Secret handling (do before commit)

- Same rules as release.md. Everything is in one tree (no submodules), so a single parent-repo `git grep` covers the whole codebase, `apitools` + `chat` included.
- Save important keys not already in `.env` into `.env` (gitignored).
- Delete secret files from the project; track rotation in `./issues/<name>.md` (rotation is the real fix).
- Pre-commit gate: `git grep --cached` for secret patterns must be clean.

## Report sections (`before-commit-report.md`)

Same 0–13 dimension set as the release report (`before-release-report.md`), but every dimension is scoped to the **uncommitted delta vs `HEAD`**:

0. High-End Overview (exec summary + readiness scorecard + verdict)
1. Changes Overview (`HEAD` → working tree: files, new/removed services, risk table)
2. Security Overview · 3. Code Quality · 4. Minimality/Repeatability/Structure
5. Declarativity · 6. Configurability · 7. Scalability · 8. Efficiency
9. Deployment/Infra · 10. Application Code Correctness (file:line, severity-ranked)
11. Feature Validation (run the FV suite, pass/fail per feature) · 12. Deployment-Context drift
13. Minimum gate to commit (blocking items)

Each dimension: be concrete (file:line), rate it, list top fixes.
