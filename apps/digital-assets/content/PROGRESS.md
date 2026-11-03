# SEO content — where it stands and how to continue it anywhere

This page is the handoff for the SEO content programme. It is enough for a fresh session to continue
the work: on the MacBook office, or inside a Claude cloud VM where DGO runs. Nothing here depends on a
session's memory.

## What the owner asked (both on the hub, Plane project DGO)

- **DGO-659** — the SEO recap, word for word (2026-10-19). Every part of it is a work item in
  `apps/project-pln/plans/seo.yaml`: 11 modules «SEO · 0…10», DGO-660…818.
- **DGO-819** — the content, word for word. All the text is written by Sonnet subagents: deep research,
  human-level Hebrew, an Israeli author's attitude, and placeholders for media. It is organised in digital
  assets by type, for the sites to read and update live. **Pure content creation is the priority.**

## What exists

| Piece | Where |
|---|---|
| The library's map, file format and import path | [README.md](README.md) |
| The writer's brief (voice, types, lengths, placeholders, research budget, checklist) | [BRIEF.md](BRIEF.md) |
| The only claims about DGO a piece may make | [FACTS.md](FACTS.md) |
| The plan: 343 pieces (35 flagships, 231 project profiles, 77 more), each with its Plane item | [assignments.yaml](assignments.yaml) |
| The written pieces | `content/<type>/<slug>.he.md` |
| The writer→editor workflow | [workflow.js](workflow.js) |
| What is done and what is left | `./bbox digital-assets content-status` (or `python3 content/status.py`) |
| Into digital assets, as drafts, idempotently | `./bbox digital-assets content [--dry-run] [--activate]` |
| The types, as blueprints | `blueprints/content-library.yaml`, `content-article`, `-project`, `-tutorial`, `-comparison`, `-directory`, `-news`, `-report`, `-post`, `-glossary` |

**The house style.** The first three pieces were reviewed: `tutorial/install-dgo-with-claude`,
`article/n8n` and `project/freecad`. They are dense, sourced (20–59 sources), honest about limits,
local (prices in ₪ at the Bank of Israel rate, Tax Authority rules), and fair to competitors. Every new
piece is measured against them.

## How the writing runs

[workflow.js](workflow.js) runs one **Sonnet writer** per job, then one **Sonnet editor** per job.
- **The writer** researches first, then writes the job's pieces and runs the brief's checklist.
- **The editor** is adversarial:
  - it holds every DGO sentence to FACTS.md;
  - it checks the five claims that matter most against primary sources;
  - it rewrites anything machine-sounding;
  - it imports the job.
- **Jobs:**
  - one long piece per job;
  - two "alternatives to X" pages per job;
  - six project profiles per job.
- **When a file exists:** if it already passes the checklist, the writer skips it. If it does not, the
  writer completes it.
- **Measured cost:** 36–48 minutes and 400–600k tokens per long piece. A workflow runs 4 agents at once on a
  6-CPU machine.

On 2026-10-19, from 23:00, four runs started on the MacBook office:
- Wave A: 72 long pieces.
- Wave B: directories, alternatives, the glossary, reports, and 230 project profiles.
- Wave C: Wave B's last 22 project jobs, in reverse order.
- Wave D: Wave A's last 30 jobs, in reverse order.

They write straight into this directory. Progress is committed and pushed to `dgo-pair` as it lands.

## Continue from anywhere — a Claude cloud VM, or any machine

1. **Check out** branch `dgo-pair` of `solomonBoltin/deployment-hacohen`, and pull it.
2. **See what is left:**
   - `python3 apps/digital-assets/content/status.py`. It needs PyYAML (`pip install pyyaml`).
   - On an office, `./bbox digital-assets content-status` does the same inside the engine.
3. **Write the remaining jobs.** In Claude Code there, paste the prompt below.
4. **Commit and push only `apps/digital-assets/content/`** to `dgo-pair` (pull first if it moved). One
   commit per batch is fine.
5. **Import on the office that runs digital assets** (today the MacBook):
   `git pull && ./bbox digital-assets content`. It adds a draft version only for files that changed.
   Activate only after review: `--activate`.

The prompt for the cloud session:

```text
Continue the DGO SEO content library (Plane DGO-659 / DGO-819). Read CLAUDE.md, then
apps/digital-assets/content/PROGRESS.md, README.md, BRIEF.md and FACTS.md.
Run: python3 apps/digital-assets/content/status.py --jobs --repo "$PWD" --no-import > /tmp/content-jobs.json
Then run the workflow apps/digital-assets/content/workflow.js with the JSON in /tmp/content-jobs.json as
its args (I opt in to the multi-agent workflow; Sonnet writers and editors, as the script says).
Every hour, and when it finishes: commit only apps/digital-assets/content/ to dgo-pair and push
(pull --no-rebase first if behind; never force). Report: status.py's table before and after.
```

## What comes after the text (in the plan, not started)

- **English:** a `-en` piece for each Hebrew piece, after the Hebrew is reviewed (BRIEF: Hebrew first).
- **Posts:** `content/post/<slug>.he.md` for every published piece. The `content-post` blueprint exists.
- **The site renders the library:** DGO-685 (seo-204), the article content model on the sites, and
  DGO-686 (seo-205), English under `/en/` with hreflang.
- **Media, layer 3:** SEO · 9, DGO-801…808. It starts only after the text passes its gate (DGO-664).
- **The site's truth:** DGO-683 (seo-202). A Sonnet agent was fixing it on 2026-10-19:
  - the licence page said fair-code;
  - about 30 source links pointed at the private repo;
  - the SEO check could not see either.
  Its result is on DGO-683.
