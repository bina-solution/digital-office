# AGENTS.md — the one entry file

Every agent that works in this repo loads this file, and only this file, when a session starts. That
includes Azaria and Raphael (the office's own agents, on DeepSeek in `bina-ds`), Claude Code, Codex,
and anyone else. It is kept short on purpose. Everything else is read when the task needs it, from the
index at the end. Why this layout, with the measurements and the research behind it:
[ai/context/azaria-context-architecture.md](ai/context/azaria-context-architecture.md).

There is no `CLAUDE.md` any more. It was a second entry file covering the same ground (2026-10-15,
DGO-646), and its operating sections now live in
[ai/context/running-the-stack.md](ai/context/running-the-stack.md).

## What this is

DGO is the digital office of BINA Solutions: a platform OS that runs an office's apps as containers
compiled from declarations. The apps include n8n + apitools OCR + WhatsApp for Hebrew financial
documents, mail, drive, INDOX, chat, the console and Plane. This repo is its infrastructure-as-code, and live
offices run it:

- the HP, on branch `hp-dgo`;
- the Mac, on `mac-dgo`;
- vps1, at `console.staging.digital-office.co.il`.

The goal is fully declarative: `git clone` + `./bbox run` (on Windows `bbox.cmd run`) brings an
office up from `.env`. `bbox help` lists every verb.

## The DGOs

"DGOs" (the owner's word, 2026-10-19) means the company's offices together, each linked to the
others: **macbook** (the owner's MacBook, Lima engine), **hp-laptop** (the HP, WSL), **vps1**
(`*.staging.digital-office.co.il`) and, since 2026-10-21, **dell** (the portable Dell,
`portable-ubuntu`, being installed from the public release) — the "square herd" — plus
**claude-cloud**, a sandbox office that joins vps1 by declaration. Both laptops reach vps1 over SSH
(each office's Computers app) and link to it with DGO Extend; MacBook ↔ HP is a LAN pair. A link that
drops is a bug, and so is one that does not come back by itself once the machines are on the same
network again. Per office: `./bbox dgo link status`. The herd's security posture, every finding and
the work plan: [ai/context/dgo-security.md](ai/context/dgo-security.md).

## How a session works

1. **One work item per session.** The item is the brief: its words, its acceptance and its
   comments (`./bbox project-pln tasks show <REF>`, project `DGO`). Read the item, then only what it
   needs. Open a doc when the task touches its subject, not before.
2. **A request is a work item first.** When the owner asks for something:
   - open an item with his own words;
   - put every file he sent on it (`tasks attach <REF> <file…>`);
   - answer him with the item's link first, at the top of the reply and through every channel that
     reaches him;
   - then run `tasks start` and work.

   This does not apply to a question, a request for a report, or "wait".
3. **Keep the item's notes in a file**: the plan, what was tried, what failed and why, and what is
   left. Re-read it before each step. When a session grows long, write the notes and end it; the next
   session starts from the item and the notes.
4. **Change → verify against real output → second reader → gates → land → report on the item.**
   - A second reader is a fresh session given only the diff.
   - Gates run on a probe commit in a worktree ([scripts/refactor/GATES.md](scripts/refactor/GATES.md)).
   - A commit names its paths explicitly. Other writers share the checkout, so never commit or
     overwrite a file you did not change.
   - The report on the item gives the commit, the proof and what is live.
5. **Never edit an entry file in the middle of a work session.** That means this file, a `SKILL.md`
   or a persona. The harness re-injects the whole file into the context. Change one as its own item.

## Non-negotiables (what may be done to production)

1. **This is production.** Real users depend on it. When in doubt, do nothing and report.
2. **Never run `docker compose` directly; use `./scripts/dc` or `bbox`.** Services are compiled into
   `.generated/` from `apps/*/app.json` + `platform.state.yaml`. A bare `docker compose` resolves
   zero services and exits 0, a silent no-op (gate G7).
3. **Explain a dangerous command before running it.** That covers `rm`, `mv`, `dd`, `chmod`,
   `chown`, `kill`, `stop`, `restart`, `sudo`, `--force`, `DROP`/`DELETE`/`TRUNCATE`, and anything
   that writes or deletes files, services or data. Say in a line what it does and what could break.
4. **Back up before destruction. Verify against real output before claiming done.** One perfect
   example, then review, then scale.
5. **Language:** answer in the language the owner wrote in. Code, commits and docs are in English.
6. **Git: commit and push on the office's own branch only.** `git rev-parse --abbrev-ref HEAD` names
   it: `hp-dgo`, `mac-dgo` and so on. Deploying is git-based, so pushing is how an office deploys and
   tests parity.
   - Hook modes are real only once committed: `git update-index --add --chmod=+x`.
   - Unless asked, never create, switch, rename or delete a branch, and never merge, rebase,
     `reset --hard`, tag, force-push or rewrite history.
   - Proven work is merged into `dgo-stable`, and offices take each other's work by merging it.
     Nothing is written twice, and nothing is re-implemented from another office's description.
   - Each office has one branch, cut from `dgo` (the owner, 2026-10-08, and again 2026-10-21: "you
     should always stay on dgo-mac and same for every other dgo should stay on his branch"):

     | office | machine | branch |
     |---|---|---|
     | macbook | the owner's MacBook (Lima engine) | `mac-dgo` |
     | hp-laptop | the HP (Windows/WSL) | `hp-dgo` |
     | vps1 | `*.staging.digital-office.co.il` | `vps1-dgo` |
     | dell | the portable Dell (`portable-ubuntu`) | `dell-dgo` |
     | claude-cloud | a Claude cloud sandbox | `claude-dgo` |

   - The branch is declared per office, `DGO_BRANCH=<branch>` in its `.env`, and held by
     `.claude/hooks/office-branch.py` (registered in `.claude/settings.json`). It refuses a commit,
     push, switch, branch write, rebase, reset, or merge of anything but `dgo-stable` that breaks the
     rule; it prints the office's branch at every session start; it only warns while `DGO_BRANCH` is
     empty. The owner's explicit ask, in chat, for one of those acts runs as `DGO_GIT_OVERRIDE=1 git …`,
     so the reason is on the command line.
   - It is a security rule, not a tidiness rule: the DGOs review found three offices on three code
     lines, so a fix proven on one office was absent on the others (S8,
     [ai/context/dgo-security.md](ai/context/dgo-security.md)).
7. **Never stall on a sub-agent.**
   - Sub-agent tasks are read-only research, time-boxed, and told "return what you have if blocked".
   - Independent sub-agents go out together, not one after another.
   - Long live work (builds, browser flows, docker) stays in the main session as a background job you
     watch.
   - Interactive browser42 driving is never handed to a sub-agent: there is one shared browser.
   - Never re-dispatch a task before reading the first run's output.
8. **Tightening a contract? Enumerate every caller mechanically first.**
   - Use a gate. Check what it scanned (the file count, not just the findings), and prove it finds
     the callers in the pre-fix code and none after the fix.
   - With no gate, stage the change: warn first, then refuse.
   - The guard's error message must survive every hop.
   - The outage behind this rule is in [GATES.md](scripts/refactor/GATES.md) § "Tightening a
     contract".

## The owner's standing rules (each said until it stuck; the count is how often)

1. **Finish the work** (×117).
   - No "shall I proceed", no menu of options, no command for the owner to run, and no waiting.
     Choose, write down why, and continue until nothing is open.
   - What only the owner can do (a password, a production decision, a hand on a machine) goes on an
     item labelled `בעלים`, and everything around it goes on.
   - A side task goes to a sub-agent, not to him.
2. **Watch what you started** (×46). No long sleeps or waiting loops. Read real progress (the log,
   the counter, the output) every 15–60 s, and show it.
3. **Fix the root, minimally and generically, and fix regressions first** (×24). Never change a test
   or a doc to make something pass. When a test does change, report it apart from the fix.
4. **See what the owner sees** (×29). QA through the console and the real addresses, in his Chrome
   for his flows: not an IP, not an app on its own (browser42 is for OAuth flows). Detect a stall or a broken screen, and prove its root, before he reports it.
5. **Answer short, and answer what was asked** (×30). Give the result first, as text, not as report
   files. A word limit he gives is the limit. A question is not an instruction (×4): answer it and
   change nothing.
6. **Declarative, and part of the OS** (×6). Nothing he has to type: no manual command, no firewall
   step, no SSH between offices. Offices are installed and linked from their screens.
7. **The item is the boundary** (×19).
   - Work inside the app the item names. Do not diagnose, rebuild or restart its neighbours.
   - Before a build, check load and disk; run one build at a time and prune after.
   - A compose edit covers the whole file, then `dc config`.
   - Before a cycle of runs, every lock is released and nothing is still running (×6).
8. **Hands off until he says otherwise.**
   - Never unpair an office or restart the MacBook's engine without him at the machine (×8).
   - INDOX's drain stays on, and drain B stays 500 (×2).
   - Files are edited with the file tools, never patched by a script (×8).
9. **Do not make him say it again.**
   - Link every n8n execution you ran.
   - The word is *instance* (מופע), never tenancy.
   - Show a substantive change nobody asked for as a plan first.
   - Carry a given task to its end.
   - In a long session, re-read his recent messages.
   - A progress report carries every measure he asked for, every time (×14).
10. **A request is a work item first** (2026-10-07). See How a session works, step 2.

11. **A display change comes back as an interactive simulation, and its screenshots** (2026-10-12).
   - «תמיד כשאתה מציע שינויים שקשורים לתצוגה תתן חזרה צילום מסך הדמייה אינטרקטיבית»: a mock he
     can drive, plus the picture of it — never a paragraph or a diagram of boxes.
   - When he presented the problem with a screenshot, the demo starts from THAT screen (×2): his own
     pixels inside the frame, the change applied to them, only the shell chrome drawn from its real CSS.
   - Every number in the demo is a measurement of its own layout, and a band a static crop cannot have
     is measured off the shot and drawn (`prep-screen-bands.py`).
   - The recipe: `prep-screen-bands.py <shot> --rows y0,y1` → `build-fullscreen-mock.py --app-shot …
     --rail-gear …` → shots at the phone profile. Workbench `digital-office/sim/`, output (gitignored)
     `ci-artifacts/fullscreen-mock/`; see `console-fullscreen-mock.src.html`.

## Layout: the directory is the layer (gate G9)

- `platform/` is layer 0, the compiler. `manager/reconcile.py` reads `apps/*/app.json` +
  `platform.state.yaml` and renders `.generated/`, which you never edit or commit by hand. Its native
  Go successor is `packaging/dgo`.
- `platform-base/` is layers 1–2, what every office gets: traefik, authentik, postgres, redis, n8n,
  connections, console, machine and the rest.
- `apps/` is layer 3: one directory per app, each with its `app.json` and its `AGENT.md` brief. An
  app never reaches into another.
- `compose.yml` holds only the shared network, `platform.state.yaml` says which apps are enabled, and
  `.env`/`.env.ex` hold config and secrets. `apitools` and `chat` are in-tree (no submodules).
- The rest:
  - `scripts/` holds `dc`, `lib.sh`, and `refactor/` (the gates);
  - `issues/` holds defects;
  - `legacy/` is the one retirement archive (G34);
  - `ai/context/` holds the docs below;
  - `ai/obsidian/` is the older memory vault (read only when an item points there);
  - `digital-office/` is the dev-only UI workbench, not a layer.

## Where context lives: read it when the task needs it

| Need | Source |
|---|---|
| Take the lead on the plan: state, recipes, the 12 steps, owner decisions, budget | [ai/context/take-the-lead.md](ai/context/take-the-lead.md) |
| The DGO herd as one business: what runs on each computer, where each app belongs (MacBook the interface, HP the always-on centre, Dell the heavy work, vps1 the public door), the HP's readiness before clients; `./bbox computers herd` checks it | [dgo-herd.md](ai/context/dgo-herd.md), [apps/computers/herd.yaml](apps/computers/herd.yaml), plan `apps/project-pln/plans/dgo-herd.yaml` (DGO-914…944) |
| DGO security for the whole herd: every finding (S1–S22), the solutions weighed, the plan, the security app; the branch rule and its guard | [dgo-security.md](ai/context/dgo-security.md), plan `apps/project-pln/plans/dgo-security.yaml`, `.claude/hooks/office-branch.py` |
| Run, build and test the stack: `bbox run`, the three environments, **Docker 29 fails silently (use 28.x)**, cloud sandboxes, `digital-office/` | [running-the-stack.md](ai/context/running-the-stack.md), [healthy-baseline.md](ai/context/healthy-baseline.md) |
| How an agent's context is built and budgeted | [azaria-context-architecture.md](ai/context/azaria-context-architecture.md) |
| Target architecture and plan, release, the native core, who owns what | [dgo-architecture-2026.md](ai/context/dgo-architecture-2026.md), [platform-os-release-plan.md](ai/context/platform-os-release-plan.md), [core-native-plan.md](ai/context/core-native-plan.md), [platform-os-consolidation.md](ai/context/platform-os-consolidation.md) |
| Writing an app, its screen, and the one palette «Olive Grove» (only `theme-tokens.css` names a colour; G27/G82) | [build-your-first-app.md](ai/context/build-your-first-app.md) |
| n8n development (export/import is `bbox n8n pull\|push`) and the raw CLI/API/DB appendix | [n8n-development.md](ai/context/n8n-development.md), [n8n-cli.md](ai/context/n8n-cli.md) |
| Services, domains, ports, networks | [deployment-context.txt](ai/context/deployment-context.txt) |
| Windows (the one way: `bbox.cmd`), macOS | [running-on-wsl.md](ai/context/running-on-wsl.md), [packaging/macos.md](packaging/macos.md) |
| A fresh machine; a fresh office in a Claude cloud sandbox | [fresh-machine-findings.md](ai/context/fresh-machine-findings.md), [fresh-office-cloud-sandbox-2026-10-15.md](ai/context/fresh-office-cloud-sandbox-2026-10-15.md) |
| Porting the simulation into the live UI; view profiles | [digital-office/sim/PORT-PLAN.md](digital-office/sim/PORT-PLAN.md), [view-profiles.yaml](scripts/ui-coverage/view-profiles.yaml) |
| Every gate, and what it scans | [scripts/refactor/GATES.md](scripts/refactor/GATES.md) |
| Everything else: the repo overview, and the folder index of `ai/context/` | [README.md](README.md), [ai/context/README.md](ai/context/README.md) |
