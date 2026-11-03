# Azaria's context — the research, the architecture, the measures

*2026-10-15, DGO-646 (the owner: «deep research on context engineering and make sure azaria session get only
united pure good context … proven context architectures for making azaria best possible performance»). For
whoever builds or runs the office's agents. Follow-ups: DGO-647, DGO-648, DGO-649.*

## 1. The finding

A model attends to every token it is given. Accuracy falls as the window fills, irrelevant text distracts it,
and contradictory instructions get obeyed or averaged rather than ignored. Azaria's context today has three
problems:

- **The entry is large.** About 23,000 tokens arrive before the owner's first word.
- **It contradicts itself.** Two instruction files cover the same ground, and the persona contradicts the
  operating rules on commit and push.
- **One session carries a whole day.** It held 22 turns and grew to 650K tokens.

The proven architectures agree on a small set of rules:

- a short, stable, single entry;
- everything else retrieved just in time;
- one task per context, with notes kept outside the window;
- compaction and clearing by policy;
- isolation for side work;
- a byte-stable prefix, so the cache can serve it.

§2 gives the evidence. §3 maps it onto Azaria's measured state. §4 is the target architecture. §5 says what
changed today and which item builds the rest. §6 lists the measures that prove it.

## 2. What is proven (the evidence)

| # | Principle | Evidence | Source |
|---|---|---|---|
| 1 | Context is a finite attention budget. Aim for the smallest set of high-signal tokens. | Design guidance from building Claude's agents. | Anthropic, *Effective context engineering for AI agents* (2025-09) |
| 2 | Accuracy degrades with input length, even on simple tasks. Distractors make it worse. | Measured on 18 models. Recall also depends on where a fact sits in the window. | Chroma, *Context Rot* (2025-07); Liu et al., *Lost in the Middle* (TACL 2024) |
| 3 | There are four failure modes. **Poisoning:** an error repeated. **Distraction:** history outweighs training. **Confusion:** irrelevant tools or text. **Clash:** contradictory instructions. | A catalogue of observed failures, each with its fix. | Breunig, *How Long Contexts Fail* / *How to Fix Your Context* (2025-06) |
| 4 | Four operations: write context out, select it in, compress it, isolate it. | A framework distilled from production agents. | LangChain, *Context Engineering for Agents* (2025) |
| 5 | Progressive disclosure. Metadata of a few dozen tokens is always loaded; the body comes when the task needs it, and linked files go deeper. | Shipped in Agent Skills, an open standard since 2025-12. The 2026 consensus treats AGENTS.md as an index, not a manual. | Anthropic, *Agent Skills* (2025-10); practitioner guides (2026) |
| 6 | One entry file read by every agent. AGENTS.md files nested closer to the code carry local rules. | An open format under the Linux Foundation's Agentic AI Foundation. Claude Code reads AGENTS.md when no CLAUDE.md exists (v2.1.277, 2026-09-18). | agents.md; InfoWorld (2026-09) |
| 7 | The KV-cache hit rate is the production metric. Keep the prefix stable, append history only, serialise deterministically, and mask tools rather than remove them mid-session. | Production experience at scale. DeepSeek V4 caches prefixes automatically on a byte-identical match, and a V4-Flash hit costs about 1/50 of a miss. Measured here: 169M cache-read tokens cost ₪2.53. | Manus, *Context Engineering for AI Agents* (2025-07); DeepSeek context-caching guide; third-party V4 price tables |
| 8 | The file system is external memory. Recite the plan at the end of the context to keep the goal in attention. Leave errors in, because the model learns from them. Avoid few-shot ruts. | Production experience. | Manus (2025-07) |
| 9 | Compaction, structured notes and context editing. When the window is full, summarise and keep decisions, files and errors. Clear stale tool results. Keep memory outside the window. | Context editing cut tokens by 84% in a 100-turn evaluation. Memory plus editing gave +39% task performance. | Anthropic, *Effective context engineering*; *Managing context on the Claude Developer Platform* (2025) |
| 10 | Intentional compaction. Research, plan and implement are separate contexts, and the window stays about 40–60% full. | Coding-agent practice on large codebases. | HumanLayer, *12-Factor Agents* (factor 3: own your context window); *Advanced Context Engineering for Coding Agents* (2025) |
| 11 | Sub-agents isolate work; they do not split a decision. A sub-agent gets a clean context and returns a condensed result. Parallel writers of one artefact conflict. Sub-agents cost about 15× the tokens. | A multi-agent research system, and a counter-case. | Anthropic, *How we built our multi-agent research system* (2025-06); Cognition, *Don't Build Multi-Agents* (2025-06) |
| 12 | A curated playbook grows by itemised, incremental deltas. Wholesale rewrites lose detail ("context collapse") or over-shorten it ("brevity bias"). | Benchmarked on agent and domain tasks. | Zhang et al., *Agentic Context Engineering (ACE)*, arXiv 2510.04618 (2025-10) |

How strong the evidence is:

- **Measured:** rows 2, 7 (cache mechanics and price), 9 and 12.
- **Consistent practitioner experience, not controlled studies:** the other rows.
- **Not benchmarked anywhere:** no study compares AGENTS.md layouts. So §6 measures ours.

## 3. Azaria today (measured 2026-10-13, [agent-context-cost-2026-10-13.md](agent-context-cost-2026-10-13.md))

| Piece | Size | What is wrong (principle) |
|---|---|---|
| System prompt: the persona plus every installed app's brief, injected whole | 8,676 tokens | The brief of an app the session never touches is distraction (2, 5). The persona restates the repo layout, so the layout has two homes, and it says "commit and push only when asked" against rule 6. That is a **clash** (3). |
| `AGENTS.md` **and** `CLAUDE.md` | ~7,200 tokens | The same ground twice, as two versions of the truth (3, 6). |
| Skill catalog | ~550 tokens | Already the right pattern (5). |
| Tool definitions | 6,626 tokens | Fine while stable. Prune only between sessions (7). |
| **Before the first word** | **≈23,000 tokens** | |
| One session: 22 turns, 450 steps | Grew to 650K of a 1M window; 169M cache reads; ₪3.78 | Every step re-reads everything (1, 2, 10). Instruction files edited mid-session were re-injected (+46K chars, 3). There were two HTTP 402 stops and four interrupted turns. |

The cost is cheap: cache hits cost about 1/50 of a miss, and 67% of the bill was cache reads. **Quality is
the expensive part:** each step reasons over a window that is two-thirds history, with the brief of every
app and two overlapping rulebooks.

## 4. The architecture: five layers, one home per fact, a budget per layer

| Layer | What it holds | When it changes | Budget |
|---|---|---|---|
| **L0 Stable prefix** (cached) | The harness system prompt; the persona (identity, language and voice only, nothing about the repo); the tool definitions; `AGENTS.md`. **No clock, no counters, no per-session data.** | Only by a release | ≤ 12K tokens; `AGENTS.md` ≤ 3K |
| **L1 Index** (cached) | One line per installed app with the path to its `AGENT.md`; the skill catalog | When an app is installed | ≤ 1.5K |
| **L2 The task** (first user turn) | The work item (words, acceptance, comments) and its notes file | Per session | ≤ 3K |
| **L3 Just in time** (through tools) | Docs, code, an app's `AGENT.md`, a skill's body, logs, read when a step needs them. Tool output is capped (head/tail, counts), and screenshots are passed as paths. | Per step | Grows; cleared by policy |
| **L4 Outside the window** | The item's notes file (plan, what was tried, what failed and why, the next step), re-read before each step; the item's comment trail in Plane, which is the durable record | Per step / per landing | Not in the window |

Policies (rows 8–11):

- **One item per session.** A new item starts a new session.
- **Compaction at 50%,** into a structured summary: files changed; tests and their results; decisions and
  why; errors word for word; the next step.
- **Stale tool results are cleared.**
- **A second reader is a new session** given only the diff.
- **Research is a sub-agent** that returns a file and one paragraph.
- **L0 files are never edited inside a work session.**
- **Budget cap:** a session that hits its ₪ cap stops and reports on the item.

## 5. What changed today (DGO-646) and what Azaria builds

**Done now:**

- `AGENTS.md` is the one entry file for every agent. It keeps every rule (non-negotiables 1–8, the owner's
  rules 1–10, the layout, the context index) and adds how a session works. It is 11.4 KB, ≈2,900 tokens;
  together the two old files were 29.9 KB, ≈7,200 tokens.
- `CLAUDE.md` is deleted. Its operating sections moved word for word to
  [running-the-stack.md](running-the-stack.md). Its index rows are in AGENTS.md's index.
- The session start no longer sends every agent through the older memory vault. The item and its notes are
  the session's memory, and the vault is read when an item points there.
- The persona's clash is fixed: commit and push happen on the office's branch only, with explicit paths,
  after the gates. This is live after the next `bina-ds` rebuild. A rebuild carries the tree, so it waits
  for the uncommitted `entrypoint.sh` of the other writer.

**Items for Azaria:**

- **DGO-647 (L1).** App briefs become an index plus on-demand reading. The persona's layout section is
  dropped, because `AGENTS.md` is its home. Target: system prompt ≤ 2,500 tokens.
- **DGO-648 (L2–L4 and the policies).** Build these in the preset and the plugins: one item per session,
  structured compaction, clearing, the notes file and recitation, a cache-stable prefix, and a meter for
  each session.
- **DGO-649.** Fix the stale references to `CLAUDE.md` in comments and docs.

## 6. How we know it worked

Report these on DGO-592's card once a week. Each has a baseline.

| Measure | Baseline | Target |
|---|---|---|
| Entry tokens (harness `contextBreakdown`) | 23,000 | ≤ 12,000 |
| Peak context per item | 650K | ≤ 200K |
| Cache-hit share | not measured | ≥ 90% |
| ₪ per closed item | not measured | Measured, then falling |
| Reopened items (a quality proxy) | not measured | Zero is the goal |

## Sources

- Anthropic, *Effective context engineering for AI agents* (2025-09) — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, *Managing context on the Claude Developer Platform* (context editing, memory tool; 2025) — https://www.anthropic.com/news/context-management
- Anthropic, *Equipping agents for the real world with Agent Skills* (2025-10) — https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- Anthropic, *How we built our multi-agent research system* (2025-06) — https://www.anthropic.com/engineering/multi-agent-research-system
- Manus, *Context Engineering for AI Agents: Lessons from Building Manus* (2025-07) — https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus
- Chroma, *Context Rot: How Increasing Input Tokens Impacts LLM Performance* (2025-07) — https://research.trychroma.com/context-rot
- Liu et al., *Lost in the Middle: How Language Models Use Long Contexts* (TACL 2024) — https://arxiv.org/abs/2307.03172
- Drew Breunig, *How Long Contexts Fail* and *How to Fix Your Context* (2025-06) — dbreunig.com
- LangChain, *Context Engineering for Agents* (2025) — https://blog.langchain.com/context-engineering-for-agents/
- Cognition, *Don't Build Multi-Agents* (2025-06) — https://cognition.ai/blog/dont-build-multi-agents
- HumanLayer, *12-Factor Agents* — https://github.com/humanlayer/12-factor-agents
- Zhang et al., *Agentic Context Engineering* (2025-10) — https://arxiv.org/abs/2510.04618
- AGENTS.md — https://agents.md ; Claude Code's AGENTS.md fallback (2026-09) — https://infoworld.com/article/4224410/claude-code-now-also-accepts-instructions-in-openais-agents-md-format.html
- DeepSeek context caching — https://api-docs.deepseek.com/guides/kv_cache ; V4-Flash prices (third-party, verify on the official page) — https://eesel.ai/blog/deepseek-v4-flash-pricing
- Codex CLI, *Context Engineering Masterclass: write, select, compress, isolate* (2026-06) — https://codex.danielvaughan.com/2026/06/19/context-engineering-masterclass-codex-cli-write-select-compress-isolate-okf-playbook/
