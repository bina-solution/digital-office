# The agent's entry context — measured, and the case for `AZARIA.md` + `DGO.md`

**Status:** reported 2026-10-13, owner's request: «תדווח על זה כמשימת יעול של עזריה ואיחוד לקובץ קונטקסט
מינימלי AZARIA.md ו DGO.md עם הפרדה בין הזהות של עזריה לקונטקסט של הלשכה. ומחיקה של claude.md ו
agents.md מפנה לdgo». Report only — the work item is `agt-014` (DGO project).

## 1. What was measured, and how

The owner pointed at a conversation
(`https://console.staging.digital-office.co.il/#/m/bina.hp-laptop?s=session-3e2f4c31-4e4d-4b2d-a61e-b2887c2482f1`).

Measured facts, in the order they were established:

* That session does **not** exist in the HP office's harness. It is a session of the **vps1** office's
  agent (`cwd=/root/digital-office`), read here over the link: the harness's own RPC
  (`POST /api/session/list`, `/api/session/page`) through the link door on `http://bina.vps1:9003`,
  with the peer's harness accepting the door's signed identity (`Host: bina.staging.digital-office.co.il`).
* Its full log was read: **2,883 events**, seq 0 → 2882 (`/api/session/follow` for the tail —
  `maxMessages` snapshot + cursor — then `/api/session/page` paged backwards to seq 0).
* The URL and the session disagree: the tile `bina.hp-laptop` is *this* office's agent served to vps1
  (`serve.only.vps1 = [plane, bina]`), while the session id belongs to vps1's own agent. vps1's console
  carries both modules with the **same** `embed: /a/bina/` (`id=bina` local, `id=bina.hp-laptop` remote).
  A session id is office-local; the shell's `?s=` is whatever the framed app reports. Worth its own
  issue — recorded here because it is what made the session hard to find.

## 2. The entry context — what the agent holds before the owner's first word

From the session's own `system/message` event (turn 1) and the messages injected beside it:

| Piece | Size | Harness count |
|---|---|---|
| System prompt — persona + the compiled brief of every enabled app's `agent.context` | 34,659 chars | **8,676 tokens** (`contextBreakdown.systemTokens`) |
| "Workspace instructions" — `AGENTS.md` **and** `CLAUDE.md` | 28,966 chars | ~7,200 tokens |
| Skill catalog (5 skills, summaries) + runtime context | 1,910 chars | ~550 tokens |
| Tool definitions | — | **6,626 tokens** (`contextBreakdown.toolsTokens`) |

**≈23,000 tokens before the first user word**, which was 64 characters
(«איך כדאי לאפשר מצב מסך מלא וחזרה…»).

Where it comes from:

* **Both instruction files are loaded, by design.** `@deepseek-ai/dsh-agent-instructions` discovers
  `AGENTS.md`, `AGENTS.local.md`, `CLAUDE.md`, `CLAUDE.local.md` (`instructionFileCandidates` /
  `localInstructionFileCandidates`). This checkout has `AGENTS.md` (15,443 B) and `CLAUDE.md`
  (14,292 B) both present, covering the same ground from two angles (repo layout, `bbox`, the three
  environments, "where context lives", `digital-office/`). The office pays for both on every session.
* **The per-app brief is the other half.** `.generated/registry/agent-context.md` is 27,515 B here and
  is injected whole, once per session, by `@bina/dsh-office-context`. Per app: computers 4,672 B,
  dgo-extend 6,101 B, office-routes 5,940 B, project-pln 6,078 B, archify 2,752 B — and the
  `## Traps` sections are the bulk (office-routes 2,720 B, project-pln 4,051 B). It exists so that
  installing an app teaches the agent to drive it (agt-003) — the intent is right, the budget is not.

## 3. What grows during a session — the real cost

Same session, 22 turns (2026-10-12 12:10 → 2026-10-13 12:20), measured from the log:

| | |
|---|---|
| Turns / steps / tool calls | 22 / 450 / 459 (367 of them `bash`) |
| Wall clock in turns | 1.68 h |
| Reasoning the model produced | **823,000 chars** |
| Tool output returned into context | 442,000 chars |
| The agent's **visible** answers | 26,000 chars (19 messages) |
| The owner's own words | ~1,000 chars (22 messages) |
| Screenshots pulled back into context | 30 (`read_image`) |
| Context pressure at the end | 650,402 / 1,000,000 tokens |
| Cache-read tokens | **169,115,648** |
| Cost meter | ₪3.78 (₪2.53 of it cache reads) |
| Model | `deepseek-official/deepseek-flash@high` |

Three amplifiers, each with a number:

1. **Every step re-reads the whole history.** At 650K pressure a 20-step turn reads ~13M tokens; that
   is where 169M cache-reads came from. One work item per session is a cost decision, not hygiene.
2. **The agent edited its own instruction files mid-session** — `AGENTS.md` at seq 449/461/737 and
   `CLAUDE.md` at seq ~1312 — and each edit made the harness re-inject the **whole file** into the
   transcript: +16.0K, +16.4K and +14.0K chars of duplicate text in one session.
3. **Six stopped turns.** Two were billing — `HTTP 402 Insufficient Balance` (turns 8 and 21) — and
   four were `interrupted` (turns 12, 17, 18, 19). One interruption was diagnosed by the agent itself:
   a `bash` call holding the turn open (`docker cp` + `sleep 75` + `tail`) was cut with no durable
   result (`issues/agent-tool-call-interrupted-without-a-durable-result.md` on vps1).

## 4. The proposal — two files, two owners, one injection each

Today three mechanisms put five kinds of text into the prompt, and two of them are unnamed files whose
purpose is "everything". The split the owner asked for makes each file answer exactly one question:

| File | Answers | Who owns it | How it is injected |
|---|---|---|---|
| `AZARIA.md` | **who the agent is** — the Hebrew persona, language and tone, what it may do without asking, what it must confirm, the owner's standing rules | the agent's own identity, shipped with the preset | the persona's `prefix`, read from the file (`!!js` + `readFileSync(new URL('AZARIA.md', baseUrl))` — the idiom `customSkillDirs` already uses), so the yaml stops carrying prose |
| `DGO.md` | **the office** — what the digital office is, the three layers and the directory rule, `./bbox`, `platform.state.yaml` → `.generated/`, where the docs live, the office's own identity (id, domain, which machines/offices it is linked to), the non-negotiables that are facts rather than behaviour | the office (the checkout) | `agent-instructions` with `instructionFileCandidates: ["DGO.md"]` and `localInstructionFileCandidates: []` — one file, one injection, no second copy |
| `.generated/registry/agent-context.md` | **what is installed and how to drive it** | the compiler, from each app's declared `agent.context` | unchanged (`@bina/dsh-office-context`) — but each app's brief gets a budget (below) |

`AGENTS.md` and `CLAUDE.md` are **deleted**, not stubbed: `README.md` (the human entry point) and every
reference in `ai/context/`, `issues/`, comments and the harness preset point at `DGO.md`. The
enumeration of callers is mechanical and comes first (AGENTS.md rule 8): `grep -rn 'AGENTS\.md\|CLAUDE\.md'`
over the tree, every hit classified as *behaviour* (must move to `DGO.md`) or *prose reference* (repoint).

### Per-app brief budget (the other half of the saving)

`agent.context` keeps: what the app is, its endpoint/capability, the 2–3 calls that drive it, and the
traps that have cost something. Everything deeper moves to the app's own `AGENT.md` (already the file
the agent is told to read when it works on that app) and is reached with the `skill` tool instead of
riding in every session. Measured ceiling to aim for: **≤1,000 B per app**, ≤8 KB in all — against
27.5 KB today.

## 5. Baseline and acceptance

Baseline to beat, measured on the entry context alone (no work done yet):

* entry context ≤ **8,000 tokens** (from ~23,000), of which the office brief ≤ 3,000;
* one instruction file, one persona file, **zero** file injected twice;
* no `AGENTS.md`, no `CLAUDE.md` in the tree; `grep -rn 'AGENTS\.md\|CLAUDE\.md'` returns only history
  (plan items, issues) that says why they are gone;
* a fresh session's first request shows exactly two office-owned sections — identity and office — and
  the compiled app brief as the third;
* and the behaviour the files exist for is unchanged: the agent still knows the owner's standing rules,
  still drives every installed app, and still answers in Hebrew.

Verification is the same read that produced this document: one session started in a fresh office
checkout, its `system/message` + injected messages measured (`/api/session/…` on the harness), plus
`./bbox reconcile render` unchanged and the gates green.

## 6. Open questions (for the owner, or decided while implementing)

1. Does `AZARIA.md` ship with the preset (an app file, changed by a commit) or live in the office
   volume (an office's own identity, changed by the owner)? The name suggests the first; the content
   is the second's business.
2. What do the *other* agents that read `AGENTS.md` today (Claude Code, Copilot, OpenHands — `AGENTS.md`
   calls itself their canonical entry point) read after the deletion? Either they learn `DGO.md` or
   `.github/copilot-instructions.md` becomes the pointer.
3. Does the compiled app brief merge into `DGO.md` at render time, or stay a section of its own? Merging
   is one file and one injection; keeping it separate is one writer each, which is the platform's own
   rule (the app declares, the compiler renders).
