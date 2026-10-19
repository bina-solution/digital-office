# context/ — index

Agent-facing context for deployment-hacohen. Entry point is [../AGENTS.md](../AGENTS.md);
this folder holds the deeper material. Each fact has **one home** (no duplication).

## Baseline & reference
| File | What |
|---|---|
| `deployment-context.txt` | Current inventory: services, domains (prod `<svc>.hacohen…` / dev `<svc>.dev.hacohen…`), networks, auth posture, run commands. Read by the health/review/report job-prompts. |
| `n8n-cli.md` | **The** n8n operate reference (tested, v2.0.3): CLI (safe/mutating/dangerous) + REST API lifecycle (create→develop→activate→execute→delete) + DB checks + workflow/credential IDs, MCP paths/gids, pull/push, lessons (OAuth, Sheets MCP timeouts). |
| `agent-deployment-investigator.md` | Read-only investigator persona (allowed/forbidden, approach, output format). |
| `local-ocr-research.md` | Local-OCR engine evaluation → PaddleOCR PP-OCRv5 (swap point in apitools). |

## Operate & build (bbox CLI + IaC)
| File | What |
|---|---|
| `../../bbox` (CLI) | **The** deployment entry point — `run/stop/reset/status/verify`, `n8n pull/push/status/verify`, `b42`, `install`, `onboarding`. Thin dispatcher over `scripts/*` (shared helpers in `scripts/lib.sh`). |
| `automation-iac.md` | The blueprint dev loop (pull→edit→push→verify), the 3 credential classes, push hardening (non-destructive + native tag import), and gotchas. |
| `n8n-cli.md` | Deeper n8n operate reference (CLI/REST/DB) that `bbox n8n *` wraps. |
| `n8n-estate-move-to-vps1.md` | Moving the 92-workflow n8n estate to the remote office: what a credential blob is, the `N8N_ENCRYPTION_KEY` drift and its fix (both halves — `.env` and the container's settings file), the import runbook, and the dump alternative (DGO-64/65). |
| `bbox-verification-loops.md` | 27 runnable end-to-end verification loops (terminal/browser42/agentic) across state combos; regression suite for the infra. |
| `workflow-state-sync.md` | active vs published vs draft (`activeVersionId`) — why push publishes. |

## Incoming-documents (indox)
| File | What |
|---|---|
| `indox-mechanical-production-plan.md` | **Canonical INDOX completion plan** — verified current state, target contracts, migrations, rollback, release gates, five-file recovery, and legacy retirement. |
| `incoming-documents-architecture-and-productization.md` | System map + responsibilities, fresh-tenant provisioning, hardcoded-coupling list, phased productization plan. |
| `incoming-documents-onboarding.md` | One-click onboarding strategy/runbook + the OAuth recipe (§8c) + run logs. |

## Setup (host / accounts)
Windows dev bring-up lives in [CLAUDE.md](../../CLAUDE.md) (the one command) and
[running-on-wsl.md](running-on-wsl.md) (what it depends on, the Docker Desktop trap, and the
`BBOX_*` variables). Who owns which fact across the platform — and what is still duplicated —
is [platform-os-consolidation.md](platform-os-consolidation.md).

The old `setup-project-development-on-windows.md` was retired: it described a manual
`docker compose` / Docker Desktop / `production/` setup that `bbox` has since made obsolete. Its
still-live n8n sync content moved into [n8n-cli.md](n8n-cli.md).

| File | What |
|---|---|
| `setup-google-cloud-login.md` | GCP login via browser42 + the `127.0.0.1:5678`-only OAuth rule. |
| `setup-facebook-login.md` | Facebook/Messenger driving recipe. |
| `browser42-cli.md` | browser42 CDP/Playwright driving guide (behind `bbox b42`). |
| `browser42-agentic-browsing-lifetime-report.md` | Full native-group/subagent incident record, evidence, failure analysis, and phased cheap-model hardening plan. Observable event integrity is recorded in `browser42-agentic-browsing-observable-ledger.manifest.json`. |
| `browser42-release-plan.md` | **Canonical Browser42 release plan** — current implementation scorecard, post-ledger cheap-agent assessment, dependency order, proof matrix, SLOs, and exact release gate. |
| `browser42-groups.md` | **Session groups design** — how stable session slugs and tab ownership groups make simultaneous agents practical without cookie isolation. |
| `release.md` | release checklist/notes. |

## Agent-runner job-prompts (functional — agent-runner loads `context/<job>-context.txt` by name)
| File | Job | Access | Output |
|---|---|---|---|
| `agent-chat-context.txt` | WhatsApp ops Q&A | read-only | ≤10-line replies |
| `agent-execute-context.txt` | "OpenPilot" coding agent | host shell | concise do-it |
| `automations-agent-context.txt` | Incoming-docs/Gmail/Drive Q&A | 1 n8n webhook call | Hebrew, doc row/status |
| `dev-agent-context.txt` | full dev dispatcher | read-write host+git+docker+db | `[think]/[done]`, !cmds, issues |
| `quick-health-context.txt` | fast triage | read | ≤60-line verdict, ≤3 min |
| `deployment-review-context.txt` | mid-depth review | read | ≤200 lines, Now/Week/Watchlist |
| `deployment-report-context.txt` | Sunday deep report | read (+ `/host` RO) | 14-section evidence report |
| `security-review-context.txt` | fast security scan | read | ≤80 lines, top-8 + fix |
| `storage-report-context.txt` | storage audit | read | where bytes go + safe cleanup |
| `deploy.propmt.txt` | deploy a new app | full + playwright verify | working deployed service |

## Lessons
| File | What |
|---|---|
| `lessons-platform-os-refactor.md` | The 12 failures-that-reported-success behind gates G31–G34, the generic CLI and the hook model — each with its evidence. Read before adding a gate, moving a file, or trusting a green board that only ran on WSL. |

## UI — the platform's own shell (המרכז)
| File | What |
|---|---|
| `platform-navigation-design.md` | **The** navigation/sidebar specification (v2, 2026-09-25): measured baseline of the live rail, the binding geometry/breakpoints/overflow/auto-collapse/a11y/RTL/motion rules, the failure-mode invariants, and the phased plan (P0 gate → P6). Section numbers §1f/§3.2/§3.5/§3.6 are cited by other docs and are stable. |
| `sidebar-research.md` | Raw evidence appendix behind the spec's §1g/§1h — numbers-first, a link per claim, judgements marked. Not binding on its own: where it disagrees with the spec, the spec wins. |
| `connection-status-standard.md` | **The** disconnection/degraded-status standard: the measured 2026-10-04 tunnel outage and why the console showed a blank frame, the normative state rules (S1–S12) and the per-hop table, the gap inventory against today's four vocabularies, and the ordered plan (P0–P7) with its acceptance and fault-injection requirements. |

## Plans / notes
| File | What |
|---|---|
| `digital-office-network-plan.md` | **The** plan for the `network` app, rev 2 (2026-09-29): a remote office behind NAT reachable at a public edge host, gateway-issued QR enrollment, per-office app sets declared through the existing `offices` app, and the `sites` → `site-runtime` split. §16 is the open-decisions table for the owner. Partially supersedes `NETWORK-APP-AND-NATIVE-SCALING-PLAN.md`. |
| `digital-office-network-architecture.md` | The independent English review of that plan — 24 findings (6 high / 13 medium / 5 low) with the amendment each forces, final user stories with acceptance criteria, orchestration (sequences, state machines, single-writer ownership), 9 diagrams (Mermaid + SVG in `diagrams/`). |
| `NETWORK-APP-AND-NATIVE-SCALING-PLAN.md` | 2026-08-11, **partially superseded** (see its own header): §1/§2/§5 — the seven measured incidents and the WireGuard-over-`ssh -R` decision — remain authoritative; its catch-all-router and node-issued-enrollment parts are replaced. |
| `core-layer-audit.md` | **Which of `platform-base/` is actually core** (2026-10-09, item core-008): all 15 manifests asked the same three questions — who declares it, does the office still start without it, what it costs — with the compiler's own closure as the evidence (`reconcile.py services --for …`). 6 strictly required, 8 required as providers, 1 removable (`machine`), plus the four capabilities whose consumers call them from code without ever declaring them. Ends with an ordered, reversible plan; removes nothing itself. |

- `bigger-plan.txt` — roadmap (declarative deploy, central agent, feature-validation as live observability, egress proxy, Traefik hardening).
- `feature-validation-next.txt` — build daily report + `online-tools`/host/tool/integration health into feature-validation.
- `n8n-optemise-plan.txt` (2025-09) — n8n perf: batching + queue mode + workers (done) + WAL/checkpoint tuning.
- `review-request.txt`, `security.txt` — short review/security prompt fragments.

## Not here (live elsewhere — don't duplicate)
- Operating charter, user profile, decisions, lessons, session log, n8n System Map → `obsidian/` vault.
- General compose command cookbook → `deployment-context.txt` (superseded the old `deployment` skill).
- Running `dc`/captures from inside the agent container (the bind-mount trap that empties
  `.generated/registry` while `healthz` stays green) → `running-dc-from-the-agent-container.md`.
