
---
name: obsidian-brain
description: "Read and write the persistent AI brain vault (Obsidian-compatible Markdown). Use when: starting a session (read orientation), remembering facts/decisions/preferences, logging session activity, checking what happened previously, creating checkpoints, searching past decisions, or documenting bugs and lessons. This is the cross-session memory — use it BEFORE doing work that might duplicate past effort."
---

# Obsidian Brain — Persistent AI Memory Vault

The vault at `/root/deployment-hacohen/ai/obsidian/` is the AI's cross-session brain.
All memories, decisions, preferences, bugs, and session history live here as
Markdown files.

## Vault Root

```
VAULT=/root/deployment-hacohen/ai/obsidian
```

## Session Bootstrap (mandatory — run at the start of EVERY session)

```bash
cat "$VAULT/00 - START HERE.md" && echo "---" && cat "$VAULT/_Hooks/ONBOARDING.md" && echo "---LAST SESSION---" && head -30 "$VAULT/Sessions/Session Log.md" && echo "---CHECKPOINTS---" && ls "$VAULT/Checkpoints/" 2>/dev/null
```

## When to write to the vault

| Trigger | Write to | Method |
|---------|----------|--------|
| Session started (meaningful work done) | `Sessions/Session Log.md` | Prepend dated entry |
| User states a preference or fact | `Memory/User Profile.md` or `Memory/Working Style.md` | Append |
| Architectural decision made | `Memory/Important Decisions.md` | Append with date + rationale |
| Bug took >15 min to find/fix | `Projects/<project>/Bug Log.md` | Append: symptom → root → fix |
| Failed approach discovered | `_Hooks/Lessons Learned.md` | Append |
| Question raised, not yet answered | `Memory/Open Questions.md` | Append |
| Mid-task pause / handoff | `Checkpoints/<slug>.md` | Create checkpoint file |
| New credential/API fact | `References/<service>/` | Create/update reference |

## Write format

Every entry MUST carry a date heading (ISO: `YYYY-MM-DD`), tags, and project marker.

Example session log entry:
```markdown
## 2026-06-12

### 🔧 Fixed X in service Y
- **Category:** #fix #service-name
- **Project:** deployment-hacohen
- **What:** description
- **Root cause:** ...
- **Verified:** what was checked
```

## Search before creating

Before any new piece of work, search the vault:
```bash
grep -rl "<keyword>" "$VAULT/" --include="*.md"
```

## What NEVER goes in the vault

- Real passwords, API keys, OAuth tokens → use `/memories/repo/` or `.env`
- PII of third parties
- Large binaries

## Vault structure (for orientation)

| Path | Purpose |
|------|---------|
| `00 - START HERE.md` | Session bootstrap + navigation |
| `_Hooks/` | Behavioral rules loaded every session |
| `_Hooks/ONBOARDING.md` | Hard rules: dangerous commands, language, context |
| `_Hooks/Operating Charter.md` | Super-rule: truth, autonomy/obedience, verification |
| `_Hooks/Problem Solving Framework.md` | 9-step path before saying "I can't" |
| `_Hooks/Lessons Learned.md` | Failure catalog |
| `Memory/` | Persistent facts about user, style, decisions |
| `Projects/<name>/00 - Overview.md` | Per-project state |
| `Projects/<name>/Bug Log.md` | Bugs that took >15 min |
| `Sessions/Session Log.md` | Dated log, newest on top |
| `Checkpoints/` | Mid-task snapshots |
| `References/` | API specs, cheat sheets, technical facts |
| `System/Runbooks/` | One runbook per failure mode |
| `Skills/` | Skill routing table |

## How the user sees this

The user does NOT edit the vault manually. The AI reads and writes automatically.
The user can say:
- "What happened last session?" → read Session Log
- "Remember that I prefer X" → write to Memory
- "Save our progress" → create checkpoint
- "What did we decide about Y?" → search Important Decisions
