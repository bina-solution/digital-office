# AGENTS.md — deployment-hacohen

Canonical entry point for any AI agent (Copilot, Claude Code, OpenHands) working in this repo.
Read this first, then the linked context below.

## What this is
The complete infrastructure-as-code for **one live production VPS** (BINA Solutions / Hacohen),
served under `*.hacohen.bina-solutions.co.il`. Core business: **automated Hebrew financial-document
processing** (invoices, delivery notes, balance sheets) via n8n + apitools OCR + WhatsApp, plus an
in-development **AI agent that builds and operates the deployment itself** (`apps/openhands`).
Goal: **fully declarative** — `git clone` + `./bbox run` brings the whole stack live from `.env`.

## Non-negotiables (operating rules)
1. **This is production.** Real users depend on it. When in doubt, do nothing and report.
2. **Never call `docker compose` directly — use `./scripts/dc` (or `bbox`).** Services are *compiled*
   into `.generated/` from `apps/*/app.json` + `platform.state.yaml`; the root `compose.yml` holds
   only the shared network. So a bare `docker compose <cmd>` resolves **zero services and exits 0** —
   a silent no-op that looks like success. `./scripts/dc` passes the compiled file list and works
   from anywhere. Enforced by gate G7 (`scripts/refactor/compose-invocation-lint.py`).
3. **Explain dangerous commands before approval** (anything with `rm > >> mv dd chmod chown kill stop restart sudo --force DROP DELETE TRUNCATE`, or that writes/deletes files/services/DB): say in 1-2 lines what it does + what could break.
4. **Back up before destruction**; **verify against real output before claiming done**; **one perfect example → review → scale**.
5. **Language:** reply in the language the user wrote in; think/code/commits/docs always in English.
6. **Version control — commit and push on the working branch; never touch branches or history.**
   `add`/`commit`/`push` are allowed on the current working branch, because deploying is git-based:
   staging and the VPS pull, so an agent that cannot push cannot deploy or test parity. Committing
   is also what makes file MODES real — `/mnt/c` reports every file as 755, Debian honours what git
   recorded, and `run_app_hooks` silently skips a non-executable hook, so an uncommitted mode is an
   untested one. Use `git update-index --add --chmod=+x` for hooks.
   **Still forbidden without an explicit request:** creating, renaming, switching or deleting
   branches; `merge`/`rebase`/`reset --hard`/`tag`/force-push; anything that rewrites history.
   Convention: all work lives on the single working branch `deployment-hacohen` — the always-published
   state; PR it into `main` to publish the public project state.
   On the DGO line the working branch is the OFFICE's own, cut from `dgo` — `hp-dgo`, `mac-dgo`, … —
   and an office's checkout commits and pushes on that branch only (the owner, 2026-10-08, after an
   agent had opened a shared `dgo-pair` by itself). What an office has proven — the gates with only
   the known reds, the windows suite, the simulation's flows — is merged into `dgo-stable`, and an
   office takes the others' work by merging `dgo-stable`; nothing is written twice. Before a
   session's first commit, `git rev-parse --abbrev-ref HEAD` names the office's branch.
7. **Subagent discipline — never stall.** `runSubagent` blocks its caller and there is no timer or
   wakeup mechanism, so stall-proof by construction: (a) every subagent task is read-only research,
   time-boxed to ≤5 minutes, and its prompt ends with "return what you have if blocked"; (b) dispatch
   all independent subagents in ONE parallel block — wall time is the longest one, never serial;
   (c) long live work (browser42 flows, sync runs, rebuilds, docker) stays in the MAIN thread via
   `run_in_terminal`, async mode for anything that keeps running — terminal notifications are the
   only real "wakeup"; (d) never hand interactive browser42 driving to a subagent (one shared
   browser, one task at a time); (e) never re-dispatch a duplicate task before reading the first
   one's output.
8. **Tightening a contract? Enumerate every caller MECHANICALLY, first — and prove the enumerator
   works before you trust its zero.** Making an interface stricter (a new required parameter, a
   refusal where there used to be a fallback, a narrowed accepted type) turns every existing caller
   that omits it into a production failure the moment it lands. So the caller list is *part of the
   change*, and it must come from a gate, not from `grep`: a manual survey silently misses whatever
   its pattern misses and reports the miss as "no callers found".
   The order is: **(1)** name the gate that enumerates callers of this interface; **(2)** check what
   it actually scanned — the file count, not just the finding count; **(3)** prove it produces a
   finding on the *pre-fix* code, then zero on the fixed code; **(4)** fix the callers; **(5)** then
   land the guard. **No gate for step 1 → the enumeration is manual → the rollout is staged (warn,
   then refuse).** Skipping the warn phase is licensed by a mechanical survey and by nothing else.
   Also: **the guard's error message only exists if every hop preserves it** — a proxy that ends in
   a bare `raise_for_status()` turns an actionable upstream 4xx into an opaque 500 with an empty log.
   This is written from an outage, not from principle: `apps/drive` did all of the above on
   2026-08-06 (repo-wide survey, ~44 call sites fixed first) and landed clean; `apps/mail` landed a
   *wider* guard three days later with no equivalent survey, and 12 unmigrated call sites in
   `apps/mail/mailview` took the client's whole mail page to 500 — while the gate that existed to
   find them (G62) read green, because its glob had only ever matched one app. Full account and the
   audit of every other gate's scan coverage: [scripts/refactor/GATES.md](scripts/refactor/GATES.md)
   § "Tightening a contract: enumerate every caller MECHANICALLY, before you tighten it".

## The owner's standing rules (each was said until it stuck)

Collected 2026-10-06 from the owner's own messages in every session of every office, July → October
2026: 37 asks that turned out to be nine rules. The number is how many times he had to say it; the
quote is his. They do not loosen rules 1–8 above — those decide what may be DONE to production,
these decide how work is carried. Where the two meet, both hold: take the path rule 1 allows, write
down what is only the owner's, and keep going with everything else.

1. **Finish the work. Never stop, park it, or hand it back** (×117 — nothing was said more).
   No "shall I proceed", no menu of options, no command for the owner to run, and no waiting for a
   person who may never answer: choose, write down why, go on to the next item until nothing is
   open. Open work lives in the hub (Plane project `DGO`, `./bbox project-pln tasks …`); what only
   the owner can do — a password, a decision about production, a hand on a machine — is recorded
   there under the label `בעלים` while everything around it continues. A side task goes to a
   sub-agent, not to him. «לעולם אל תעביר לי משימות!!! יש לך את היכולת לעשות הכל!»
2. **Watch what you started** (×46). No long sleeps and no waiting loops: read real progress — the
   log, the counter, the sub-agent's output — every 15–60 seconds, 2–5 minutes at the very most for
   a long job, and show it. «no long sleeps!! max 60s better 15s»
3. **Fix the root, minimally and generically — regressions first** (×24). One simple, stable fix
   where the defect is; nothing layered on top, nothing over-built. A test or a document is never
   changed to make something pass, and when a test does change it is reported apart from the fix.
   What used to work and broke is repaired before anything new.
   «וגם הקוד צריך להיות מינימלי ונקי כמו זהב טהור»
4. **See what the owner sees** (×29). QA in his own Chrome, through the console and the real
   addresses — not an IP, not an app on its own, not a new tab per step (browser42 is for OAuth
   flows). Notice a stall or a broken screen yourself, and prove its root, before he reports it.
   «make sure you see the same thing i see and detect them on your own»
5. **Answer short, and answer what was asked** (×30). Text, not report files; the result first; no
   walls of words; a word limit he gives is the limit. And **a question is not an instruction**
   (×4): asked "why" or "what", answer — do not change, delete or revert.
   «no dont prune!!!! i asked a question»
6. **Declarative, and part of the OS** (×6). Nothing the owner has to type: no manual command, no
   firewall step, no SSH between offices — an office is installed and linked from its screens, in
   any order. «הכל חייב להית דקלרטיבי וחלק מהOS»
7. **The item is the boundary** (×19). Work inside the app the item names; its neighbours are not
   diagnosed, rebuilt or restarted. Before a build check load and disk, one build at a time, prune
   after; a compose edit is the whole file, then `dc config`, before anything else. Before a cycle
   of runs every lock is released and nothing is still running (×6).
8. **Hands off until he says otherwise.** An office is not unpaired and the MacBook's engine is not
   restarted without him at the machine (×8). INDOX's drain stays on and drain B stays 500 (×2).
   Files are edited with the file tools, never patched by a script (×8).
9. **What he should not have to say again.** A link to every n8n execution you ran. The word is
   *instance* (מופע), never tenancy. A substantive change nobody asked for is shown as a plan first;
   a task that was given is carried to its end (×6). In a long session re-read his recent messages
   and keep the list of what he asked (×7). A progress report carries every measure he asked for,
   every time (×14).
10. **A request is a work item first** (2026-10-07, said to every office's agent). When he asks for
   something, before any of the work: open it as a work item in the hub with his own words, put
   every file he sent on it (`./bbox project-pln tasks attach <REF> <file…>`), answer him with the
   item's link, and only then start (`tasks start`). Not for a message that only asks a question,
   asks for a report, or says to wait. «when I send request like this alwase mange it with an
   workitem in projectpln with all my attachments and reply (also you also azaria) with the link to
   the workitem and then start working on it»
   **The link is the first thing he gets** (×2, the same evening): the address itself, at the top
   of the reply, sent before any other step and through every channel that reaches him where he
   is. A link written in the middle of a long turn did not reach him — «עדיין לא קיבלתי קישור!!!
   … תמיד קודם תביא את הקישור».
11. **A display change comes back as an interactive simulation, and its screenshots** (2026-10-12).
   «תמיד כשאתה מציע שינויים שקשורים לתצוגה תתן חזרה צילום מסך הדמייה אינטרקטיבית» — a proposal about
   what a screen looks like is not a paragraph and not a diagram of boxes: it is a mock he can drive,
   plus the picture of it. **And when he presented the problem with a screenshot, the demo starts
   from THAT screen** (×2, the same day): «הדמייה שכוללת את מה שהמסך הקיים שמופיע בצילום ואז את
   השינויים והדגמה אינטרקטיבית» — his own pixels inside the frame, the change applied to them, and
   only the shell chrome drawn (from its real CSS). A drawn stand-in for the app is what the first
   version was, and it was not enough: the screen he sent IS the subject of the picture.
   Two rules that follow: every number in such a demo is a measurement of the demo's own layout (never
   a figure typed in by hand — this caught a rule the proposal was missing, `.embed{inset:0 0 60px 0}`
   leaving a 60px hole the moment the tab bar went), and a band that a static crop cannot have — the
   app's rail runs the whole height — is measured off the shot and drawn (`prep-screen-bands.py`).
   The recipe: `prep-screen-bands.py <shot> --rows y0,y1` → `build-fullscreen-mock.py --app-shot …
   --rail-gear …` → shots at the phone profile. Workbench: `digital-office/sim/`, output (gitignored):
   `ci-artifacts/fullscreen-mock/` (montage + per-state PNGs). See `console-fullscreen-mock.src.html`.

## Layout

Three layers, and **the directory is the layer** — where a file lives declares what it may depend on
(enforced by gate G9, `layering-lint.py`).

```
platform/          LAYER 0  the compiler. manager/reconcile.py reads every apps/*/app.json plus
                            platform.state.yaml, resolves capabilities, and renders .generated/.
                            Depends on nothing above it.
platform-base/     LAYER 1-2  the substrate every deployment gets: traefik, authentik, postgres,
                            redis, n8n, connections (the credential broker), console, machine, …
apps/              LAYER 3  the products, one directory per app, each with an app.json manifest:
                            chat, indox, drive, mail, my-docs, apitools, supabase, openhands, …
                            An app declares what it needs; it never reaches into another app.

.generated/        RENDERED OUTPUT — never edit, never commit-by-hand. compose.yml + overlays +
                   registries + the authentik blueprint. Produced by `bbox reconcile`.
compose.yml        the shared external network, and nothing else (see rule 2).
platform.state.yaml  which apps are enabled, provider bindings, perf profile.
.env / .env.ex     config + secrets (DEPLOYMENT_DOMAIN, *_BASE_URL, …)
scripts/           dc (the compose wrapper), lib.sh, baseline.sh, refactor/ (the gate registry)
ops/ packaging/    operational tooling and the measured optimisation study
ai/context/        agent context: baseline, architecture reviews, plans (see ai/context/README.md)
ai/obsidian/       persistent cross-session memory vault (the "brain")
issues/            tracked defects with severity/status front-matter
digital-office/    NOT A LAYER — the dev-only UI design/spec workbench (no app.json, no compose
                   service, no bbox verbs, never shipped, never run by CI). sim/build.mjs bundles
                   the REAL frontends + mocks into platform-sim.html (the spec the live UI is
                   ported toward, see sim/PORT-PLAN.md); tooling/ assembles platform-mockup.html.
                   Only scripts/ui-coverage/{live-ui-map,sim-live-parity,pixel-diff}.py read it.
                   Full boundary: CLAUDE.md § "What digital-office/ is (and is not)".
```

`legacy/` is the **retirement archive** — workflows moved there are import-ineligible (the n8n
blueprint loader only reads `apps/*/blueprint/n8n/`, and G34 `legacy-ref-lint` fails any live code
that references `legacy/` without an explicit allowlist entry). What it holds is listed in
[legacy/README.md](legacy/README.md) — among it `legacy/n8n/indox-sheets-era/` (5 retired
Sheets-era workflows, 2026-08-04). `attic/` is gone: it came back as a second archive (211 files,
2026-08-16 to 08-21) and was folded into `legacy/` on 2026-10-06 — one archive, one gate.
`build.mjs` takes its feature-validation dashboard from `apps/apitools/feature-validation/`.

`bbox` is the single entry point: `./bbox run` brings the stack up on any machine, `bbox help` lists
the tree. n8n export/import is `bbox n8n pull|push` (the old `scripts/n8n-pull` / `n8n-push` no
longer exist); n8n ops → [ai/context/n8n-cli.md](ai/context/n8n-cli.md).

## Where context lives (each fact has one home)
| Need | Source |
|---|---|
| **Healthy-baseline proof** (one-command fresh reset→build→up→tests→ui-map) | [ai/context/healthy-baseline.md](ai/context/healthy-baseline.md) (`bbox baseline`) |
| Services, domains, ports, networks, run commands | [ai/context/deployment-context.txt](ai/context/deployment-context.txt) |
| n8n operate (CLI/API/DB, workflow+credential IDs, MCP paths/gids, lessons) | [ai/context/n8n-cli.md](ai/context/n8n-cli.md) |
| Everything else in `ai/context/` — agent-runner job-prompts, investigator persona, plans, OCR research | [ai/context/README.md](ai/context/README.md) (folder index) |
| Operating charter, user profile, decisions, lessons, session log, **n8n System Map** | `ai/obsidian/` vault (start: `ai/obsidian/00 - START HERE.md`) |

## Session start
Read `ai/obsidian/00 - START HERE.md` and `ai/obsidian/_Hooks/ONBOARDING.md`; check `ai/obsidian/Sessions/Session Log.md` (top) and `ai/obsidian/Checkpoints/`. Write lessons/decisions back to the vault while working. Vault read/write is handled by the `obsidian-brain` skill (`.github/skills/obsidian-brain/`).
