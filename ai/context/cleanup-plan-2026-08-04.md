# Comprehensive Cleanup Plan — 2026-08-04

Produced from a live scan of the repo, the private Docker engine, and the live n8n DB
(`data/_runs/cleanup-scan{,2,3,4}.sh`). Ordered by risk-vs-payoff. Every "delete" step below
states exactly what it removes and why it is safe.

## What was verified today (facts the plan stands on)

- **Live n8n DB is already clean of the retired sheets-era code**: zero rows for
  `indoxDocUploader01` / `indoxDocCreate01` / `indoxApiSheets01` / `indoxSetupWF001` / `logger01`,
  zero webhook registrations matching `upload-document` / `incoming_document` / `indox`.
  The consolidation (commit `b7213294`) left nothing dangling in the DB.
- **40 active workflows, all executed within the last day** — no dead active workflows, except
  `Balance Sheet JQ Ex V3` (active, never executed).
- **bbox status**: 39/45 up, 33 healthy; the 4 `browser42-*` containers are DOWN (Created);
  n8n: 77 wf (76 active/76 published), blueprint clean.
- **Issues**: 14 files — 4 closed + 5 resolved (archive candidates), 8 open + 2 in-progress
  (2 critical, 3 high, 3 medium, 3 low).
- **Scratch**: 24 untracked files (`tmp/*`, `tmp_*.sql/.py`); `data/_runs/` holds ~387 helper
  scripts (gitignored — local disk only).
- **Doc drift**: AGENTS.md/CLAUDE.md claim "legacy/ and attic/ are gone (0 tracked files)" but
  `legacy/n8n/indox-sheets-era/` now tracks 5 files (moved there this session).

---

## Phase 0 — Zero-risk hygiene (do first, no service impact) — **DONE 2026-08-04**

| # | Action | What it removes / changes | Why safe |
|---|--------|---------------------------|----------|
| 0.1 | Delete the 24 untracked scratch files (`tmp/*`, `tmp_*.sql`, `tmp_parse_q*.py`) | One-off diagnostic probes from past sessions; nothing references them (`grep` for each name in tracked files returns nothing) | Untracked, no build/CI references |
| 0.2 | Add `tmp/` and `tmp_*` to `.gitignore` | Prevents recurrence | Additive only |
| 0.3 | Triage `data/_runs/` (~387 scripts, gitignored) | Keep what CI/bbox/docs reference; delete one-off session probes (audit*.out, b42_*, tmp_* etc.) | Local-only dir; deletions cannot affect the stack |
| 0.4 | Fix doc drift: update the "legacy/ is gone" sentence in AGENTS.md + CLAUDE.md to describe `legacy/n8n/indox-sheets-era/` as the intentional retirement archive (import-ineligible, G34-gated) | 2 lines of docs | Docs only |
| 0.5 | Issues sweep: move the 4 `closed` + 5 `resolved` issues to `issues/archive/`; re-triage the 10 active ones against today's state | File moves + status lines | Docs only |

All 0.1–0.5 executed 2026-08-04: 24 scratch files deleted + `.gitignore` `tmp/`,`tmp_*` (0.1–0.2);
`data/_runs/` pruned with pre-prune manifest (0.3); AGENTS.md legacy paragraph rewritten, CLAUDE.md
clean (0.4); 10 closed/resolved issues `git mv`'d to `issues/archive/` (+ `$schema=../schema.json`
hint fix), 10 active issues stamped with the 2026-08-04 re-triage verdicts (0.5). Gate-safety of
both the `app.json` doc-keys and the issues move was verified against every relevant gate
(`reconcile.py validate()` + G13/G25 ignore unknown `use[]` keys; G32/G9/G34/G33 exclude `issues/`
by prefix, so `issues/archive/` stays excluded).

**Verify:** `git status -s` shows only intended changes; G34 (`legacy-ref-lint`) still PASS.

## Phase 1 — Security (the 2 critical + 2 high issues)

Order by blast radius; **back up before each**, one at a time, verify routing between steps.

1. **`traefik-docker-socket-rw` (critical)** — traefik + portainer bind `/var/run/docker.sock`
   read-write. Add a socket-proxy service (e.g. `tecnativa/docker-socket-proxy`, read-only caps)
   and point both at it. *Risk: routing breaks if proxy caps are wrong → verify every route +
   authentik forward-auth afterwards.*
2. **`n8n-postgres-publicly-exposed` (high, in-progress)** —
   `platform-base/n8n/docker-compose.yml:74-75` publishes `10001:5432` on all interfaces.
   Scope to `127.0.0.1:` (or the VPN subnet) like the UI publish already is.
3. **`local-routers-host-spoof-bypass` (high, in-progress)** — add
   `middlewares=authentik@file` to the 4 remaining `-local` routers (n8n-local, glitchtip-local,
   portainer-local, authentik-local) and add a local-only ipallowlist middleware.
4. **`n8n-encription-rotate` (critical, open)** — finish the rotation runbook (partially landed).
   Highest-risk item: **snapshot n8n DB + credential blobs first**, rotate in a maintenance
   window, verify all 24 creds decrypt.

**Verify:** fresh `./bbox ui-map` + manual login checks; `issues/` statuses updated with evidence.

## Phase 2 — INDOX/chat consolidation leftovers — **DONE 2026-08-04 (except 2.3 time-boxed)**

1. **End-to-end upload — REDEFINED BY OWNER 2026-08-04.** Root cause of the 503: INDOX forwarded
no `connection_id`, drive resolved to the bound Google Service Account, which cannot upload (a SA
has no personal Drive storage and no Shared Drive grant) → Google 403 → 503 → INDOX 502. Owner's
decision: the SA upload refusal is CORRECT behaviour. Implemented:
   - `apps/drive/adapters/google_sa.py`: `create_folder` / `upload` / `op_upload` /
`op_create_from_text` now raise an explicit, actionable `GoogleAuthError` ("SA supports
list/download/move/rename/delete only; use the local drive engine (admin profile) or an OAuth
user connection for uploads") instead of surfacing an opaque Google 403 as a bare 503.
   - `apps/indox/app/incoming_documents/api/__init__.py`: uploads now default to the drive app's
LOCAL engine, `admin` profile, into an auto-created `indox/uploads` folder (lazy
find-or-create via `GET/POST /api/folders`, id cached; degrades to drive-root if the folder
can't be resolved). An explicit `folderId` or `profile_id`/`connection_id` override from the
caller is still respected as-is, so remote-engine uploads keep working when requested.
   - `apps/indox/app.json`: the `drive` use[] entry now documents the dependency (local engine +
admin profile + `indox/uploads` folder) — verified safe: reconcile + G13/G25 ignore unknown keys.
   - INDOX therefore depends only on LOCAL engines for everything it needs to work out of the
box, and remains separately proven to work on remote engines (drive, mail).
2. **Chat startup check** — the n8n `setting` webhook is the LEGACY admins source; admins are now
owned by chat (per-connection botAdmins) + the INDOX API. `checkN8nSettings()` demoted to
advisory: reports WARN (never FAIL), wrapped in try/catch so a timeout reads as a warning.
3. **Sunset gate (time-boxed, after 1–2 weeks green) — NOT now.** Remove the legacy fallbacks
(`N8N_UPLOAD_DOC_WEBHOOK`, `INCOMING_DOCS_WEBHOOK`, `N8N_*_USER/PASS`) from
`apps/chat/src/config.js` + compose env, retire the `Upload Doc To API TOOLS` workflow if
unreferenced, and clean stale mentions in `.claude/settings.json` / `apps/chat/next.txt`.
4. **`Balance Sheet JQ Ex V3`** — DOCUMENTED, not retired: it is referenced by
`JQExV3RunBS00001.json` (`cachedResultName`) as the Execute-Workflow target, and belongs to the
JQExV3 family whose callers are the Python BFF (`apps/indox/app/incoming_documents/extraction.py`),
not the n8n pipeline — zero n8n executions is expected. Noted in `retired-code-and-workflows.md`.

**Verify:** live upload test returns a drive `webViewLink`; chat report shows no FAIL.

## Phase 3 — Platform hygiene (medium/low)

1. **browser42 DOWN containers** — reaper/task-runner/task-watchdog/browser sit at `Created`.
   Either bring them up (if the wedge issue is resolved) or gate them out of compose until
   `issues/browser42-crash-leak-slowdown.yaml` is fixed. Decide; don't leave 4 permanently-down
   services in `bbox status`.
2. **`authentik-outdated-cves` (medium)** — bump `ghcr.io/goauthentik/server:2024.12` (3 refs in
   `platform-base/authentik/docker-compose.yml`) with a blueprint backup + restore drill first.
3. **`authentik-hardening` (medium)** — password-policy/HIBP blueprint entries + CSP middleware.
4. **`apitools-vision-key-rotation` (medium)** — rotate in the GCP console (off-tree); containment
   already verified in-repo.
5. **`.ci-cd/ui-map` (79 tracked files)** — confirm these are meant to be tracked artifacts vs.
   build output; if output, gitignore + remove.

**Verify:** `./bbox status` shows no permanent `Created` services; `bbox baseline` still green.

## Phase 4 — Governance / close-out

1. **Push** — `platform-os-refactor` is ahead of origin; user must run
   `git push origin platform-os-refactor` (credentials blocker).
2. **Anti-recurrence** — the `.gitignore` from 0.2 plus a periodic sweep habit (session-end
   `git status -s` check) keeps scratch from piling up again.
3. **Vault** — record decisions (folderId policy, fallback sunset date, browser42 gating) in
   `ai/obsidian/` per the onboarding hook.

---

## Suggested execution order

```
Phase 0 (all, ~1 commit)  →  Phase 2.1+2.2 (functional)  →  Phase 1.2, 1.3 (low-risk security)
→  Phase 1.1 (socket proxy)  →  Phase 1.4 (rotation, maintenance window)  →  Phase 3  →  Phase 4
```

Each phase is one commit (or one per security item) on `platform-os-refactor`; no amend/rebase/
force-push; every destructive step backed up and verified against live output first.
