# context/ — index

Agent-facing context for digital-office. Entry point is [../../AGENTS.md](../../AGENTS.md), the one entry file every agent loads;
this folder holds the deeper material. Each fact has **one home** (no duplication).

## Baseline & reference
| File | What |
|---|---|
| `business-domains.md` | **The business domains** (DGO-2048, DGO-2101): «זהות» (us — `digital-assets`, brand.v1), «ישויות» (everyone else — people and organizations with roles customer / supplier / company / salesperson / contact, entities.v1) and «מסמכים» (documents only: parties by id + a snapshot at issue). One home per fact, both core apps on in every office, the patterns, the contract, what moves and in what order. |
| `provider-apps.md` | **How DGO implements an outside service** (DGO-1473): a generic app per domain of work + one provider app per service (`<generic>-<service>`, found by name), `external` vs `engine`, the access ladder (official API → the web app's own API → the browser), the four channels, sign-in by itself, consent. Worked example: `apps/domain-internic`. |
| `dgo-net.md` | **DGO net — the public front** (DGO-1757): the owner's goal of 2026-11-10 in his words (one app on Bina's server serving ten public services: accounts, apps, news, operative collective, domains, compute, public-route, llm, dgo cloud, payments; each a generic DGO app, organised by DGO net), what the office already has for each and what is missing, and where the research lives. Research only: nothing built. The id `dgo-net` is taken by the WireGuard container. |
| `office-backup.md` | **Office backup** (DGO-1505): what an office holds (measured, classed secret / git / irreplaceable), the four existing backup paths and their gaps, the design (restic through the generic drive protocol to a chosen office/engine/account/folder, a consistent export per kind, keys held apart, schedule, retention, checks, drills), restore paths and «continue quickly» in minutes. Plan: `plans/office-backup.yaml` (module `ob`). |
| `deployment-context.txt` | Current inventory: services, domains (prod `<svc>.example…` / dev `<svc>.dev.example…`), networks, auth posture, run commands. Read by the health/review/report job-prompts. |
| `n8n-cli.md` | **The** n8n operate reference (tested, v2.0.3): CLI (safe/mutating/dangerous) + REST API lifecycle (create→develop→activate→execute→delete) + DB checks + workflow/credential IDs, MCP paths/gids, pull/push, lessons (OAuth, Sheets MCP timeouts). |
| `agent-deployment-investigator.md` | Read-only investigator persona (allowed/forbidden, approach, output format). |
| `local-ocr-research.md` | Local-OCR engine evaluation → PaddleOCR PP-OCRv5 (swap point in apitools). |
| `local-asr-research.md` | Local Hebrew speech-to-text: ivrit.ai Whisper benchmarked on the office's 2-vCPU box, for apitools (2026-10-06). |
| `speech-platform-plan.md` | Speech in the office: 2026's transcription API standards, the capability the office serves, and the end-to-end plan (2026-10-07). |
| `digital-office-owner-guide.md` | The owner's guide, in Hebrew: how the Digital Office works today, how to run it, and what is left before everything runs from it. |
| `digital-office-story.md` | The Digital Office in the owner's words (DGO-1307): the source for every sentence the sites, the business plan and the deck say. |

## Operate & build (bbox CLI + IaC)
| File | What |
|---|---|
| `../../bbox` (CLI) | **The** deployment entry point — `run/stop/reset/status/verify`, `n8n pull/push/status/verify`, `b42`, `install`, `onboarding`. Thin dispatcher over `scripts/*` (shared helpers in `scripts/lib.sh`). |
| `app-instances.md` | **App instances («מופעים»)** (DGO-1920): more than one copy of an app on one office (three Claude Desktops, each its own account) — the model, `bbox apps instance` and the apps screen's «מופע נוסף», the generated `instances/` root both compilers read, which apps can be copied and why, the research behind it, the limits. |
| `wrapped-official-app.md` | **A wrapped official app** (DGO-1259): the vendor's own Linux client as the screen (Selkies), its headless side behind a contract, one volume for the sign-in; the four channels, the `wraps` declaration and gate G108, the check before a wrap enters the catalogue. Starting files: `apps/_template-wrapped/`. |
| `app-cli-api-standard.md` | **The app CLI and API standard** (DGO-1243): what the screen does, the API and the CLI do. The grammar `dgo <app> <noun> <verb>`, `--json` on every verb, exit codes 0/1/2/3, help, secrets, writes, canonical ops. What holds today and what comes with cli-202…206. |
| `automation-iac.md` | The blueprint dev loop (pull→edit→push→verify), the 3 credential classes, push hardening (non-destructive + native tag import), and gotchas. |
| `n8n-estate-move-to-vps1.md` | Moving the 92-workflow n8n estate to the remote office: what a credential blob is, the `N8N_ENCRYPTION_KEY` drift and its fix (both halves — `.env` and the container's settings file), the import runbook, and the dump alternative (DGO-64/65). |
| `bbox-verification-loops.md` | 27 runnable end-to-end verification loops (terminal/browser42/agentic) across state combos; regression suite for the infra. |
| `archive/indox-pre-2026-09/workflow-state-sync.md` | active vs published vs draft (`activeVersionId`) — why push publishes. |
| `healthy-baseline.md` | `./bbox baseline`: the one-command from-scratch proof that the platform comes up and every surface works. |
| `low-memory-mode.md` | Low-memory mode: what to stop to free engine RAM when DNS and the Docker API go flaky under memory pressure. |
| `n8n-as-code-migration.md` | n8n as code (shipped 2026-08-16): `.workflow.ts` files, `bbox n8n pull/push`, the proofs and the known boundary. |
| `n8n-development.md` | n8n development in one page (DGO-584): two writers, live is the truth, the pull/edit/push loop. |

## Incoming-documents (indox)
| File | What |
|---|---|
| `incoming-documents-architecture-and-productization.md` | System map + responsibilities, fresh-tenant provisioning, hardcoded-coupling list, phased productization plan. |
| `incoming-documents-onboarding.md` | One-click onboarding strategy/runbook + the OAuth recipe (§8c) + run logs. |
| `indox-python-feasibility.md` | Can INDOX's automation leave n8n for Python (DGO-233)? Yes, 1:1 or better, by a shadowed strangler in six phases with the existing suites as the oracle. Measured: 70 workflows, 10,837 production JS lines. |
| `indox-expected-behaviour.md` | The INDOX operator spec (2026-06-26): sync_registry, one front door, a loaded demo reaches COMPLETED in ~10 min. |
| `indox-per-type-fixture-architecture.md` | Config-only document types: a type is settings rows, run by generic engine workflows (2026-07-03). |
| `indox-demo-onboarding-architecture.md` | INDOX clean onboarding + demo: reset → onboarding → rest, three welcome and three small demo documents, deterministic. |
| `indox-performance-profiles.md` | Resource-matched work progression: apitools queue inflation measured, and the perf profiles in `platform/profiles/perf-profiles.yml`. |
| `indox-testing.md` | `bbox indox test`: the suites, the pins, the authoring rules, the CI lane and the integration-API backends. |
| `AUDIT-FINDINGS-2026-08-05.md` | The INDOX deep audit of 2026-08-05: 12 «a bounded query taken as the whole truth» defects (the poller's 1000-row cap…); an open issue cites finding M2. |
| `THE-PLAN-V2.md` | The 2026-08-06 INDOX scale-build plan (5,000+ documents a month, 50k end to end); history, still cited (§F) by a plan item. |
| `lane-d-n8n-consolidation-2026-08-06.md` | Lane D, 2026-08-06: the n8n consolidation 66→38 and its dead code, measured; cited by `fixtures/schema.sql`. |
| `archive/` | `archive/indox-pre-2026-09/`: INDOX plans, RCAs and reviews from before the 2026-09-02 consolidation — history, cited by live files. |

## Setup (host / accounts)
Windows dev bring-up lives in [running-the-stack.md](running-the-stack.md) (the one command; the operating sections of the former `CLAUDE.md`) and
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
| `office-browser-in-hp-and-the-human-handoff.md` | **The owner's plan for the office's useful browser** (2026-10-14): the browser lives in the HP office and is signed in to Google/WhatsApp/GitHub so the agent works alone; when a human step is unavoidable (first sign-in, 2FA, captcha, QR) the owner gets ONE link to the exact window, openable from anywhere. What is measured today, what is missing, and the ordered work — DGO-567 (app-057…059, ui2-076, lnk-035, own-032). |
| `release.md` | release checklist/notes. |
| `browser42-agentic-browsing-observable-ledger.jsonl.gz` | The compressed event ledger behind the browser42 lifetime report; its manifest is `browser42-agentic-browsing-observable-ledger.manifest.json`. |
| `browser42-final-architecture.md` | browser42's delegated-browsing end state (2026-08-04): the activity-clock watchdog, runner v2, spans. |
| `browser42-handoff-from-domains.md` | What `apps/domains` needs from browser42 (2026-09-23): the MCP interface it uses, and the evidence for a solid link. |
| `browser42-resource-and-load-report-2026-09-22.md` | browser42 and the office measured on 2026-09-22 (4 cores, 4.9 GiB): the 1456 MiB peak behind its compose limit. |
| `captcha.md` | Human-verification challenges and the office browser (DGO-504): the measured Turnstile case, what passes in 2026, what we do. |
| `central-business-system-keys.md` | The master table of every `.env` key (purpose, consumer, kind, required, default) and the recovery when `.env` is lost. |
| `gmail-onboardin-imap-stmp.md` | Gmail for IMAP/SMTP automation by app password, no API/OAuth: what an account needs, and the `GMAIL_IMAP_*` keys. |

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
| `fresh-machine-findings.md` | Eight bugs only a genuinely fresh machine found (the n8n import race…), each invisible on a warm one. |
| `symlinked-repo-root-empty-bind-mount.md` | A symlinked REPO_ROOT emptied every relative bind mount while the containers stayed healthy (measured 10-01, fixed 32ddb392). |
| `dgo-extend-azaria-findings.md` | Three dgo-extend traps measured live on 2026-10-01 (DGO-30/32), e.g. a peer's `policy drop` killing vps1's published ports. |

## UI — the platform's own shell (המרכז)
| File | What |
|---|---|
| `platform-navigation-design.md` | **The** navigation/sidebar specification (v2, 2026-09-25): measured baseline of the live rail, the binding geometry/breakpoints/overflow/auto-collapse/a11y/RTL/motion rules, the failure-mode invariants, and the phased plan (P0 gate → P6). Section numbers §1f/§3.2/§3.5/§3.6 are cited by other docs and are stable. |
| `sidebar-research.md` | Raw evidence appendix behind the spec's §1g/§1h — numbers-first, a link per claim, judgements marked. Not binding on its own: where it disagrees with the spec, the spec wins. |
| `bina-ui-recipe.md` | Why Bina holds at every size (computed columns, the width measured on the frame) and the gap to the office's apps (2026-09-27). |
| `chat-port-plan.md` | Porting the sim's chat client onto the live chat app: the component gap measured on 2026-07-29. |
| `console-desktop-working-memory.md` | The console as a working-memory desktop, from Scott Jenson's Akademy 2026 talk: the ideas, their sources, the plan. |
| `console-dock-capacity-design.md` | The dock's capacity spec (shipped 2026-10-05): `dock-budget.js`, the «עוד» door, the launcher; held by dock-fit-lint. |
| `console-release-signoff.md` | The console's 2026-07-14 release sign-off; history, kept because `platform-navigation-design.md` cites its 238px limitation. |
| `console-url-state.md` | The link is the view (the owner, 2026-08-24): view state lives in the URL, action state never; the pattern per page. |
| `dgo55-56-proof-protocol.md` | DGO-55/56: the one command, and what counts as proof for the comparative beauty score of bina-ds against mailview. |
| `dgo55-56-results.md` | DGO-55/56 results: the beauty score measured on two offices, the defect named wherever a half could not be measured. |
| `sim-to-live-backend-audit.md` | For each behaviour the sim shows, does a live endpoint exist? Two apps need endpoints; mail threading is new. |
| `ui-program-plan.md` | The plan for one real design line across the office (2026-09-27): the beauty score, seven dimensions, phone mode. |
| `connection-status-standard.md` | **The** disconnection/degraded-status standard: the measured 2026-10-04 tunnel outage and why the console showed a blank frame, the normative state rules (S1–S12) and the per-hop table, the gap inventory against today's four vocabularies, and the ordered plan (P0–P7) with its acceptance and fault-injection requirements. |

## Plans / notes
| File | What |
|---|---|
| `dgo-herd-design.md` | **The herd in the final product** (the owner, 2026-11-05: «a solid mature stable secure ready to market solution» for every topology): one vocabulary (hub, centre, control point, gateway, grant, guest herd); his requirements as service levels; every mechanism that connects offices today, by layer, with its state; the morning's outage measured (vps1's host nft against the security sensor's, the relay nobody switched on, images older than their code, a pair that gave the public hub the vault); the design — the owner's three secrets as root, hub authority and member certificates, one join, a signed herd file, one embedded mesh (tsnet + Headscale, gated on six hard cases; NetBird the fallback), one gateway per office with verified identity and grants, herd services; every situation; security; how it sits in `dgo` and one «העדר» app; the migration and the decisions. Plan `herd-release` (DGO-1354…1379). |
| `herd-from-anywhere.md` | **Every office reaches every office, wherever the laptop is** (the owner, 2026-11-01, from a coffee shop): what held and what died off the home LAN; step 1, landed (`hub: vps1`, `bbox via`, project-pln's fallback through the hub); the lasting design — the hub's door splices ciphertext of declared pairs (phase 5, end-to-end WireGuard, no routing at vps1), path selection and the upgrade back to direct, the roaming fix, an outbox, herd-wide compute, regional relays at scale. Plan `herd-anywhere` (DGO-1094…1103). |
| `digital-office-network-plan.md` | **The** plan for the `network` app, rev 2 (2026-09-29): a remote office behind NAT reachable at a public edge host, gateway-issued QR enrollment, per-office app sets declared through the existing `offices` app, and the `sites` → `site-runtime` split. §16 is the open-decisions table for the owner. Partially supersedes `NETWORK-APP-AND-NATIVE-SCALING-PLAN.md`. |
| `digital-office-network-architecture.md` | The independent English review of that plan — 24 findings (6 high / 13 medium / 5 low) with the amendment each forces, final user stories with acceptance criteria, orchestration (sequences, state machines, single-writer ownership), 9 diagrams (Mermaid + SVG in `diagrams/`). |
| `NETWORK-APP-AND-NATIVE-SCALING-PLAN.md` | 2026-08-11, **partially superseded** (see its own header): §1/§2/§5 — the seven measured incidents and the WireGuard-over-`ssh -R` decision — remain authoritative; its catch-all-router and node-issued-enrollment parts are replaced. |
| `platform-os-release-plan.md` | The platform-OS target architecture and the plan to release, with its measured-state block (gates, layer-0 references, hooks). |
| `platform-architecture-review.md` | The 2026-07-29 platform architecture review (understand, clear, minimise, scale), every figure tagged; cited by the root README. |
| `review-claims-verdicts.md` | Verdicts on the architecture and leak claims the capped multi-agent reviews never reached (G5.1). |
| `central-business-system-master-map.md` | July's map of folding the estate into one business system, with the text/QR/OAuth key problem; a plan item still cites it. |
| `release-endgame-backlog.md` | The release endgame backlog of 2026-07-08 (API config, apitools speed, a five-minute CI lane); history, cited by a plan item. |
| `core-layer-audit.md` | **Which of `platform-base/` is actually core** (2026-10-09, item core-008): all 15 manifests asked the same three questions — who declares it, does the office still start without it, what it costs — with the compiler's own closure as the evidence (`reconcile.py services --for …`). 6 strictly required, 8 required as providers, 1 removable (`machine`), plus the four capabilities whose consumers call them from code without ever declaring them. Ends with an ordered, reversible plan; removes nothing itself. |

- `bigger-plan.txt` — roadmap (declarative deploy, central agent, feature-validation as live observability, egress proxy, Traefik hardening).
- `feature-validation-next.txt` — build daily report + `online-tools`/host/tool/integration health into feature-validation.
- `n8n-optemise-plan.txt` (2025-09) — n8n perf: batching + queue mode + workers (done) + WAL/checkpoint tuning.
- `review-request.txt`, `security.txt` — short review/security prompt fragments.

## The herd: links, remote apps and security
| File | What |
|---|---|
| `kadima.md` | **«קדימה» — the procedure** (DGO-1820): when the owner says it, six stages with an owner and a clock each (gather, sweep, cut, prove, distribute, show), four lanes at full pace, «waiting for X» is not an end state, the idle sweep, the board with six office rows. «קדימה <word>» is a meeting first (DGO-1847). |
| `kadima-meeting-to-product.md` | **«קדימה» from a meeting to a live product** (DGO-1847): the word resolved to a meeting; a product the meeting decided gets its own Plane project, `product.json` and `requirements.json`; sources, research, a reference app mapped live, reuse, own accounts and the way in, domain and mail through the registrar app, the site in the sites app, the beauty gate. `./bbox meet kadima <word> --live` lists what is missing. Born from the eleven directions «קדימה exx» needed. |
| `dgo-herd.md` | The herd as one business (DGO-911): the MacBook the interface, the HP the centre, the Dell heavy work, vps1 the public door; where each app runs. |
| `dgo-herd-os.md` | DGO as the herd's OS (the owner, 2026-11-02): access levels, doors, identity, secrets and links from one control point. |
| `dgo-extend-plan.md` | DGO Extend, the 2026-09-30 decision: remote offices, links and placement; §13 records what changed since. |
| `dgo-extend-azaria-runbook.md` | What was left on the remote-office lane on 2026-10-01 (DGO-30/32); history, cited as «full detail» by `dgo-remote-apps.md`. |
| `dgo-pairing-contract.md` | The contract for pairing two installed offices from their screens: fields, lanes, states (2026-10-04). |
| `dgo-link-lifetime.md` | Every way the vps1↔HP link dies, who notices and who repairs it (measured 2026-10-12), and what a lasting link needs (lnk-030). |
| `dgo-remote-apps.md` | Remote apps as one layer-0 feature: a linked office's apps appear in the app manager, the console, the CLI and the API, marked remote. |
| `fleet-colours-and-animals.md` | A colour and an animal per office (the owner, 2026-10-09): the three he named, and where each half lives in code. |
| `moving-an-office.md` | Moving an app or a whole office between computers with its data and a way back: computers moves bytes, dgo-extend moves apps. |
| `dgo-security.md` | DGO security for the herd (2026-10-21, DGO-824): S1–S22 re-measured, the solutions weighed, the work, the branch rule. |
| `security-plan-2026.md` | The 2026 pentest and public-security blueprint of the estate on a public VPS; its findings now live in `dgo-security.md`. |
| `dgo-security-session.md` | The owner's exported conversation on securing Compose apps on a VPS, verbatim (DGO-461); the reference for the sec-* layers. |
| `dgo-security-session.pdf` | The original PDF of that conversation. |

## Platform and app contracts
| File | What |
|---|---|
| `build-your-first-app.md` | Building an app: the manifest field by field on `apps/hello-bina/`, gate G9, the Olive Grove palette (G27/G82). |
| `platform-apps.md` | How an app works: the folder-with-a-manifest contract (app.json, compose, hooks); the companion of `platform-operating.md`. |
| `platform-operating.md` | Operating the platform: the layer shape, the compiler's verbs, finding state, installing and removing apps. |
| `platform-os-refactor.md` | The platform-OS refactor's design and parity protocol: three layers, every capability an app (Fuchsia, Cloudron… as prior art). |
| `platform-language.md` | The office's language (DGO-971): one variable for every screen, who writes it, how a UI reads it, four traps. |
| `app-catalog.md` | The signed app catalog: index-v1 + an Ed25519 signature + deterministic zips; publishing an app and installing it by URL. |
| `app-engine-pattern.md` | The engine/profile/binding pattern every backend-facing app implements: private and remote engines, five slots. |
| `profiles-and-engines.md` | Engines, profiles and profile-connections: the cross-app contract and its vocabulary, with each app's gaps. |
| `identity-and-people.md` | People and private-engine users: the shared user/person model for app engines; its framing superseded by `profiles-and-engines.md`. |
| `agent-contract.md` | `agent.v1`: the one office-agent interface (bina-ds first), loopback reach, auth, and the `bbox agent` client. |
| `browser-session-connection.md` | `browser_session.v1`: how an app acts inside a service with no API, through the owner's signed-in office browser. |
| `web-engine.md` | The web engine: a slow, human-gated web UI as a backend (cache, jobs, a change feed); in production for `apps/domains`. |
| `platform-service-contract.md` | The platform service + secret-base contract v1: connection → container → item, the protocols, frozen so apps build in parallel. |
| `platform-service-connection-architecture.md` | Platform services own their connections (drive, mail), not n8n: the target architecture behind the service contract. |
| `secret-base-design.md` | secret-base: the connections service as the one place to view, edit, rotate and connect every secret (the term mail and drive code use). |
| `architecture-map.md` | The map of the office (DGO-1800): what DGO is for, how it is built, every app and every file, with the source map beside it; July's map it replaces is in `archive/indox-pre-2026-09/`. |

## Apps — one app's deep reference
| File | What |
|---|---|
| `chat-service-plan.md` | chat from one WhatsApp bot to a chat service: local and remote backends behind connections, one adapter API (mail's pattern). |
| `chat-buzz-engine-plan.md` | chat's local engine replaced by a block/buzz relay (2026-09-02); it reverses only §3 of `chat-service-plan.md`. |
| `chat-backend-research.md` | Chat backend, adopt or build (2026-07-29): BUILD, Mattermost the runner-up; superseded by the buzz plan, still cited by plans. |
| `mail-multi-tenant.md` | One deployment per company: how mail is addressed and its DNS; the authority `.env.ex` and GO-LIVE.md §9 point to. |
| `mail-organizer-refactor.md` | The mail label engine moved into the mail app as the organizer (done 2026-08-05, closed 09-03); cited by mailapi and mailview. |
| `mail-labels-and-rules.md` | Mail labels and rules, the two «label engines»; superseded on 2026-09-03 by the organizer as the one rules store. |
| `plane-selfhost-research.md` | Plane self-hosted (2026-09-28): what runs, in Hebrew, on the office's engine, and what project-pln should be. |
| `sites-content-mapping.md` | The sites and digital-assets templates (startup and business website), their slots and assets (2026-10-02, DGO-683). |
| `seo/` | Website content data and the DGO content style guide (seo-006, DGO-665): facts, names and communities read by digital-assets. |

## Not here (live elsewhere — don't duplicate)
- Operating charter, user profile, decisions, lessons, session log, n8n System Map → `obsidian/` vault.
- General compose command cookbook → `deployment-context.txt` (superseded the old `deployment` skill).
- Running `dc`/captures from inside the agent container (the bind-mount trap that empties
  `.generated/registry` while `healthz` stays green) → `running-dc-from-the-agent-container.md`.

## Architecture review (2026-10-14, DGO-593)
| File | What |
|---|---|
| `dgo-architecture-2026.md` | **The architecture review the owner asked for**: the ten challenges as the last 100 work items state them, the 54 stated design decisions mapped to keep / move / retire (every one with `file:line`), the measured reality of the release machinery, the 2026 state of the art per dimension (pattern, precedents, networking, identity, API+CLI, UI, OS, omni-binary, registry, data), the recommended architecture judged against the owner's bar (minimal dependencies · max secure · zero duplication · minimal coupling · simplicity · generality · zero feature loss · minimal bytes), a 12-step plan with acceptance, rollback and budget, and the eight decisions only the owner can make. |
| `code-config-state-data.md` | **§8 of the architecture review, a proposal (DGO-361)**: where code, config, platform state and data live, for a client fork. Prior art (Claude Code, Docker Desktop, gcloud, n8n); a declaration in git vs a record in the office's data directory; install per OS (source vs the `dgo` binary, what is real and what is planned); 16 changes, each with its file; three points that are the owner's to decide. |
| `research/archmap-layer0-compiler-state-cli.md` · `research/archmap-link-identity-edge.md` · `research/archmap-ui-apps-data.md` | The three read-only decision maps of the source (branch `hp-dgo` @ `7347f738`): pipeline, every stated decision with its reason and rejected alternative, invariants, failure classes, smells with evidence. |
| `research/packaging-state.md` | The release machinery measured: Go tests run natively, binary sizes per target, what a double-clicked installer does today, plan-vs-reality per part, code risks. |
| `research/architecture-2026.md` · `research/bootstrapper-signing-size.md` · `research/omni-binary-and-registry.md` · `research/package-registry.md` · `research/android-path.md` | The five research briefs — every claim with a source URL and date — on platform-OS precedents and patterns, the signed bootstrapper (size floor measured), the single-binary base and the registry at apps.net.digital-office.co.il, the package format, and what Android can and cannot run. |
| `research/challenges-from-the-100-items.md` | The challenge inventory as DGO-491…591 state it: today's implementation, what the items measured, the gap against the owner's bar. |
| `binary-release-plan.md` | The owner's binary-release plan of 2026-10-14: a ≤5 MB installer, layer 0 in Go, layer-1 apps from the store, the budget. |
| `core-native-plan.md` | The core as native binaries (core-005, DGO-481): what must exist before a container is native, and the build order. |
| `core-go-forward-auth.md` | Replacing authentik with a Go forward-auth service (core-006): what authentik does here, measured, and the migration. |

## Leading the work, and the agents' context (2026-10-15)
| File | What |
|---|---|
| `official-apps-bar.md` | The bar each official app is held to against its market leader (DGO-1507): mail vs Gmail, drive vs Google Drive, meet, chat, tasks, the console, Bina, INDOX. It sets the shell's eight rules and measured phone and desktop targets. |
| `take-the-lead.md` | The plan from A to Z for whoever takes the lead (DGO-635). It covers the state, the safety rules, the recipes, the 12 steps, the workstreams, the backlog and the owner's decisions. §J says Azaria executes, Claude directs, and what the DeepSeek budget is. |
| `azaria-context-architecture.md` | How an agent's context is built (DGO-646): 12 proven principles with their sources, Azaria's measured context, the five layers with their budgets, and the measures. |
| `running-the-stack.md` | `bbox run`, the three environments, Docker and traefik (ask the daemon, not its version), cloud sandboxes and `digital-office/`. These are the operating sections of the former `CLAUDE.md`. |
| `agent-context-cost-2026-10-13.md` | What one Azaria session cost, and why: ≈23K tokens before the first word, 650K at the end, ₪3.78. |
| `session-timeline-2026-10-14.md` | The 10-14/15 session as a worked example (DGO-644): every owner message, the direction taken at each, the behaviours worth copying, and the mistakes with the rule each one left. |
| `fresh-office-cloud-sandbox-2026-10-15.md` | A fresh office in a Claude cloud sandbox: three runs, three fixes, and the pairing of an office that cannot be dialed. Taken from the branch `ccr-7412490e-ocnhhd`. |
| `OWNER-MESSAGES-FULL.md` | The owner's 249 directives from 2026-07-23 on, verbatim and in order; cited by GATES.md, plans and an issue. |
| `agent-economics.md` | The owner's 2026-11-03 ruling as rules (DGO-553): nothing spends without a change, ₪1 a day for self-activated work, no self-continuing session. |
| `agent-routine-budget.md` | «עזריה שגרה»: nothing runs unattended without an approved item with budget left; the lanes, the cost per item, the 2026-10-13 incident. |
| `automatic-progress.md` | What a self-driving step must produce, and what happens when it produces nothing (DGO-1294); a design for the owner's approval. |
| `owner-decisions-2026-10-14.md` | Azaria's 2026-10-14 page for the owner: what was decided alone, and the questions only he can answer. |
| `the-plan-2026-10-14.md` | Azaria's work plan of 2026-10-14 for the owner's approval: the order, what needs his signature, three questions. |
| `session-8a989787-post-mortem-2026-10-11.md` | What session-8a989787 really did over 2026-10-09…11, from its own record, git and the board. |
| `new-company-office-playbook.md` | Setting up a new company's office, phase by phase, from what Example shop' setup taught us (2026-10-22…30, DGO-1037): what to do, what went wrong, what the product does now, the owner's decisions and the gaps still open. No client data. |

## Client systems (Exampleu since 2026-11-09, DGO-1494)
| File | What |
|---|---|
| `facility/` | `facility/facility-model.md`: the research and model map for managing a facility, a gym first (DGO-1615) — a sister of Exampleu's models. |
| `exampleu/assets-model.md` · `exampleu/examplem-io-model.md` · `exampleu/loans-model.md` | The research and model map of each of Exampleu's three systems (DGO-1497/1498/1499): what the meeting exu101 said, checked at its full transcript; how mature systems model the domain; the Israeli rules with their sources; entities, an ER diagram, states, flows, reports, permissions, what stays open until their Drive is connected, and the first build order. Plans: `apps/project-pln/plans/exampleu-{assets,examplem-io,loans}.yaml`. |
| `exampleu/research/*-sources.md` | The three outside researches behind them, every claim marked verified / secondary / unverified with its URL; the loans one holds the worked test vectors. |
| `exampleu/archify/*.architecture.json` | The three model maps drawn as archify diagrams (DGO-1629). They are served by archify on Exampleu's office ONLY: copied into its checkout's `apps/archify/diagrams/`, untracked there, never into this repo's `apps/archify/diagrams/` (every office would show them). After an edit here: copy them over and run `./bbox archify validate` there. Change them with the model maps (v2 after their Drive). |
