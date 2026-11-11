# DGO-1642 — Obsidian out of the box: a vault that arrives full of the office's context

Research item from the product review of Exampleu's office (`bina-261109-vjlwcr`, MEET-28, 2026-11-09),
lane handed over by the MacBook's coordinator. **Nothing here was installed, enabled or changed on a
live office.** Every claim about our own code names the file it was read in; the facts marked
«measured» were read today in this checkout and on the HP.

**Recommendation: do not ship a hand-written starter vault — COMPILE one, the same way the office
already compiles the agent's brief (`render_agent_context`) and the console's tiles.** A new
`render_vault(cat, order)` step in `platform/manager/reconcile.py` writes `.generated/vault/` from a
declared manifest (`apps/obsidian/vault.yaml`): one note per enabled app (from its own `AGENT.md`,
already compiled today), the office's identity and inventory, a curated set of `ai/context` docs,
archify's diagrams, and — only on the business's own machines — the herd. An app hook copies the
changed notes into the vault volume; a gate fails when a new `ai/context` doc is neither published nor
explicitly excluded, so the vault cannot silently drift. And the vault is mounted into `bina-claude` /
`bina-ds` at `/workspace/vault`, so a session opened on the office folder can start from it. Details,
the sources, the freshness rule and the client-office boundary follow.

---

## 1. What the owner asked, in his words

> «ברגע שאני מתקין לשכה … אני מקבל את אובסידיאן … שהוא כבר מלא … כרגע אובסידיאן ריק … הוא אמור להגיע
> כבר עם מידע על הלשכה הדיגיטלית, על הארכיטקטורה שלה, על האפליקציות» [59:05–59:34]
>
> «כשאני … מתחיל סשן חדש … על הלשכה הדיגיטלית שלי, אז אוטומטית … שהוא יקבל גישה לאובסידיאן שרץ בתוך
> הלשכה … שהסוכן ידע שיש אובסידיאן … ולהבין מאיפה הוא אמור להתחיל ולאסוף שם את הקונטקסט … כי זה
> האפליקציה ברירת מחדל לקונטקסט» [59:44–1:01:01]

The acceptance on the item: **a new office gets an Obsidian vault holding the office's context (what
it is, the installed apps, the architecture); a Claude session opened on the office folder reads from
it at the start of the session.** Measured on Exampleu's office. Related: DGO-1275.

Read plainly: three asks — (1) not empty on install, (2) it holds *the office's own* context, and
(3) an agent can be told where to start and finds it. Plus an unstated but obvious fourth: it must be
**true tomorrow** — a vault that is right on day one and stale on day thirty is worse than an empty
one, because an agent will trust it.

---

## 2. What exists today, measured

### 2.1 The app

`apps/obsidian` — one container (`nobbe/ignis:0.8.16`, pinned), the **real** Obsidian downloaded from
its official source on first start, served on `obsidian.<host>` and framed in the console
(`module.external: true`). Three named volumes: `obsidian_vault` (the vault), `obsidian_state`,
`obsidian_app`. The vault is **one folder, one copy**: `${OBSIDIAN_VAULT_HOST}` when the office names an
absolute host folder (a synced vault on a laptop), else the named volume.

Its own brief (`apps/obsidian/AGENT.md`) is already honest about the boundary, and it names the gap this
item closes:

> «The office agent does not mount the vault on this line yet (bina-ds has no `/workspace/vault` here;
> EXW's branch has it, and porting it is cyc-272 item 7).»

It also fixes the ownership rule the design must not break: **the notes are the owner's, except
`Operatives/`** — the agent reads `Operatives/README.md` before running a recurring job, writes a new
operative from the README's template, and appends a line to its `Run log` afterwards.

### 2.2 What "out of the box" means today — a seed that is not what was asked for

`apps/obsidian/hooks/prepare` — **an UNTRACKED file in this checkout** (`git ls-files apps/obsidian/`
lists only `AGENT.md`, `app.json`, `docker-compose.yml`, `frame-shim.sh`; `app.json` declares
`"hooks": null`). It runs anyway, because `bbox run` calls `apps/<id>/hooks/prepare` **by convention**
(`run_app_hooks prepare`, "each app's OWN bootstrap; bbox names none of them"). So today:

* the seed exists only in one working tree — a fresh clone, a client machine, the VPS or the Dell
  would come up with an empty vault, which is exactly the owner's complaint;
* it copies `ai/obsidian` **once**, gated by a `.office-seed` marker file, and never again;
* its volume fallback is a hardcoded `digital-office_obsidian_vault` — **the wrong project name for
  this office** (the compose project here is `mydgo`; measured: `docker volume ls` shows
  `mydgo_connections_vault` and no obsidian volume at all).

And `ai/obsidian` itself — 27 notes, 220 KB — is **another deployment's brain, five months old**:

* `00 - START HERE.md` opens with «the smart-assistant brain of **digital-office**» and a reading
  order for a generic AI assistant;
* `Projects/digital-office/` holds that office's own noise — `Night Report 2026-06-19.md`,
  `Chess Game.md`, `Chat Analysis 2026-06-12.md`, `High-Load Supervised Run 2026-06-23.md`, plus two
  genuinely useful notes (`Incoming Documents — Verified Runbook.md`, `n8n System Map.md`);
* nothing in it names this office's apps, this office's architecture, or the compiled briefs.

So the answer to «אובסידיאן ריק» is not "copy harder": shipping that folder to a client hands them
another office's notes. **The seed is the wrong mechanism; the compiler is the right one.**

### 2.3 The compiler pattern that already exists, and is the model

`platform/manager/reconcile.py:3528` `render_agent_context(cat, order)` compiles every ENABLED app's
brief into one file — `.generated/registry/agent-context.md`, **1,457 lines** on this office — from
`app.json`'s `agent.context` → `apps/<id>/AGENT.md`. Its own docstring is the argument for this item:

> "the agent's prompt used to name apps by hand … That is a list living in the wrong owner's file, so it
> can only ever be as current as the last person who remembered to edit it. Same disease as console's
> hand-written tiles … and the same cure: the app DECLARES and the compiler renders it."

A vault is the same disease with bigger symptoms: 151 `.md` files and **28 MB** under `ai/context`, so
"publish all of it" is not a design — a curated, declared subset is.

### 2.4 What the agent can reach today

* `bina-claude` and `bina-ds` bind **the repository** at `/workspace/office` (and the host path) — and
  nothing else (`apps/bina-claude/docker-compose.yml:70-75`, `apps/bina-ds/docker-compose.yml:98-106`).
  The vault is not mounted anywhere the agent can read.
* the compiled briefs (`agent-context.md`) are loaded into the office agent's session automatically, so
  a line in an app's `AGENT.md` **is** a line in every session — that is the channel that makes «שהסוכן
  ידע שיש אובסידיאן» true without editing an entry file.
* a Claude Code session on the office folder starts from `AGENTS.md` and from the `SessionStart` hook in
  `.claude/settings.json` (`office-branch.py --session`), which already prints the office's branch —
  the same channel can print one line naming the vault and its start note.

### 2.5 What is available to be rendered

| source | what it gives | size |
|---|---|---|
| every enabled app's `AGENT.md` | what the app is for, its doors, its ops, its traps | 1,457 lines compiled |
| `platform.state.yaml` + `.generated/registry/office.apps.json` | what is installed, the office's identity | — |
| `ai/context/` | the platform's own documentation: `dgo-architecture-2026.md`, `app-engine-pattern.md`, `build-your-first-app.md`, `azaria-context-architecture.md`, `platform-service-contract.md`, `deployment-context.txt`, `running-the-stack.md`, `healthy-baseline.md` | 151 files / 28 MB total — a declared subset |
| `apps/archify/diagrams/*.json` | 6 diagrams (office, the link, bring-up, an app's move, sign-in on a new host) | ~100 KB |
| `apps/computers/herd.yaml` + `ai/context/dgo-herd.md` + `dgo-security.md` | the business's offices and the security posture | **herd scope** |
| `DGO_OFFICE_ID` (measured: `hp-laptop`) | which office this is — and it matches an id in `herd.yaml`'s `offices:` | the scope test |

---

## 3. The design

### 3.1 One declared manifest

`apps/obsidian/vault.yaml` — the only place that says what a vault holds. Data, not code, exactly like
`herd.yaml` and the providers catalog:

```yaml
# what a fresh vault holds, and where each note comes from
scope:
  herd_when: [DGO_OFFICE_ID in apps/computers/herd.yaml:offices]   # else: office scope only
notes:
  - { to: "Office/00 - מה זו הלשכה.md", from: ai/context/dgo-architecture-2026.md, scope: office }
  - { to: "Office/איך מרימים את הלשכה.md", from: ai/context/running-the-stack.md, scope: office }
  - { to: "Office/המצב הבריא.md", from: ai/context/healthy-baseline.md, scope: office }
  - { to: "Architecture/דפוס המנוע.md", from: ai/context/app-engine-pattern.md, scope: office }
  - { to: "Architecture/אפליקציה ראשונה.md", from: ai/context/build-your-first-app.md, scope: office }
  - { to: "Architecture/הקונטקסט של הסוכן.md", from: ai/context/azaria-context-architecture.md, scope: office }
  - { to: "Architecture/חוזה השירות.md", from: ai/context/platform-service-contract.md, scope: office }
  - { to: "Herd/העדר.md", from: ai/context/dgo-herd.md, scope: herd }
  - { to: "Herd/אבטחה.md", from: ai/context/dgo-security.md, scope: herd }
generated:
  - index                      # "00 - START HERE": identity + reading order + the hand-written area
  - apps                       # one note per ENABLED app, from its compiled brief
  - inventory                  # what is installed, where each app's screen is, its capability
  - diagrams                   # archify: a note per diagram, linking the office's own tile
excluded:                      # named, with a reason — an unexplained exclusion is a leak waiting
  - { path: ai/context/research, why: "research drafts; the conclusions live in the docs that cite them" }
  - { path: "ai/context/*-2026-08-0*.md", why: "one-off QA/audit reports from August" }
```

### 3.2 The compiler

`render_vault(cat, order)` in `platform/manager/reconcile.py`, next to `render_agent_context`, writing:

```
.generated/vault/
  00 - START HERE.md            the index: which office this is, what is installed, where to start
  Office/<identity>.md          the deployment's own facts (.env's public half: name, domain, protocol)
  Office/<inventory>.md         every enabled app: capability, endpoint, tile alias, its own one line
  Apps/<app>.md                 one note per enabled app — its AGENT.md verbatim, with front-matter
  Architecture/<doc>.md         the declared ai/context subset, verbatim, with its source path
  Herd/<doc>.md                 only when the scope test passes
  .vault-manifest.json          {note: {source, source_sha256, rendered_sha256, at}} — for the sync
```

Every generated note carries front-matter:

```yaml
---
generated: true
source: ai/context/running-the-stack.md
source_sha: 3f9c…
at: 2026-11-09T18:40:12Z
---
```

**A note that is derived is rewritten; a note that is a person's is never touched.** That is the whole
ownership rule, and it is a boundary the existing `AGENT.md` already draws ("the notes are the owner's,
except `Operatives/`"). Concretely: `Office/`, `Apps/`, `Architecture/`, `Herd/`, and
`00 - START HERE.md` are the compiler's; `Notes/`, `Projects/`, `Sessions/`, `Operatives/`,
`Memory/`, `_Hooks/` are the person's and the agent's, and no render ever writes there. The first line
of the start note says which is which, in Hebrew, so a person never has to guess.

### 3.3 The sync into the vault

`apps/obsidian/hooks/prepare` is **replaced** (and this time committed) by a hook that:

1. waits for the app to be up (as `prepare` already can);
2. compares `.generated/vault/.vault-manifest.json` with the copy it keeps on the vault
   (`.office/vault-manifest.json`) and writes only the notes whose `rendered_sha256` changed — a
   no-change sync is zero writes, which is what makes it safe to run at every bring-up;
3. never deletes: a note whose source is gone **stays** in the vault and is marked `stale: true` —
   knowledge that is old beats knowledge that vanished;
4. seeds `Operatives/README.md` and `Notes/` **once**, only if absent (the useful half of the old seed,
   and the operative template the `AGENT.md` already promises).

And the same function is the verb: **`./bbox obsidian sync`** — idempotent, prints what it wrote, so a
person can see the vault come up to date. It runs on `bbox run` (the `prepare` hook) and on demand.

### 3.4 Staying current — the gate, not the habit

`scripts/refactor/vault-sources-lint.py`:
**every file under `ai/context/` must be either declared in `vault.yaml` or named in its `excluded:`
with a reason; a new one fails the gate until someone decides.** Same shape as G9 and G27 — the
declaration is the thing that cannot be forgotten, and "it stayed current" stops being a promise.

Two more, cheap:
* the render is deterministic — same sources in, byte-identical notes out — so a diff in
  `.generated/vault/` is a real change and never noise;
* the office's `flow` gets one event when the *app set* changes (`vault.apps.changed`, app added or
  removed), because that is the moment a person's vault grows a section they did not write.

### 3.5 The agent reads it — three channels, no entry-file edit

1. **The office agent (`bina-ds`)** already loads the compiled briefs of every enabled app every
   session. `apps/obsidian/AGENT.md` therefore gets three lines that need nothing else: the vault is at
   `/workspace/vault`, `00 - START HERE.md` is the office's map, and `Operatives/` is the one place it
   writes. This is the cheapest and strongest channel — it is already compiled, already loaded, and it
   travels with the app (installed → the brief is there; disabled → it is not).
2. **The mount**: `bina-claude` and `bina-ds` gain
   `obsidian_vault:/workspace/vault` (read-write; the brief governs what may be written, exactly as it
   governs the checkout). A Claude session opened on the office folder is therefore *on* the vault too.
   Behind a compose guard: an office with no obsidian volume must not fail to start — a named volume
   is created by docker, so the mount is safe, and a `OBSIDIAN_VAULT_HOST` office mounts that path
   instead (declared, never guessed).
3. **Claude Code on the office folder**: one line from the existing `SessionStart` hook
   (`.claude/hooks/office-branch.py --session`) — «הכספת של הלשכה: `/workspace/vault`, התחל מ-
   `00 - START HERE.md`» — printed only when the path exists. That is not an entry-file edit (which the
   session rules forbid mid-item): the hook is the channel, and it already prints at every start.

### 3.6 What a client office gets — the boundary, stated and enforced

A client office's vault holds **that office and nothing else**:

* **no herd**: `ai/context/dgo-herd.md`, `ai/context/dgo-security.md` and anything derived from
  `apps/computers/herd.yaml` (the business's four machines, their addresses, their roles, every
  finding) are `scope: herd`, and the scope test is `DGO_OFFICE_ID ∈ herd.yaml:offices` — on a client
  machine that is false, and it **fails closed**: no herd note, and a note is never rendered "just in
  case";
* **no other client's data**: the render reads only the repo and the *compiled* registry — never a
  database, never another app's volume, never `apps/indox/storage`, never a document. The inventory
  note names the apps; it does not name anyone's customers;
* **no secrets**: `.env` is never read into a note (the identity note takes `DEPLOYMENT_NAME`,
  `DGO_OFFICE_ID` and the public host only), the rendered files are the repo's own docs, and the
  vault volume is not in the render path at all — the compiler writes into `.generated/`, and the hook
  copies notes in;
* **no `ai/obsidian`**: the old starter folder is retired from the seed (its two genuinely useful notes
  become ordinary `ai/context` docs if the owner wants them), because it is another deployment's brain
  and it names it;
* and the exclusion list is **printed** by `./bbox obsidian sync` ("what this vault does not contain"),
  so "what a client gets" is a fact on the operator's screen and not a claim in a document.

---

## 4. Risks, and what would make this wrong

1. **Overwriting the owner's notes.** The single worst outcome. Mitigated by the front-matter rule
   (only `generated: true` notes are ever rewritten), by the hook writing ONLY the compiler's own
   paths, and by a test that plants a hand-written note in each compiler-owned folder and asserts it is
   preserved.
2. **A stale vault that reads as truth.** Mitigated by the gate (§3.4) and by `stale: true` markers
   instead of deletion. The start note carries its own `at:` date, so a person can see the vault's age
   at a glance.
3. **Volume/2 copies.** The vault is one folder, one copy (`apps/obsidian/AGENT.md` is emphatic). The
   sync writes into the vault it is given — `OBSIDIAN_VAULT_HOST` or the named volume — and never
   creates a second one. A host-folder vault edited from a phone can produce `conflicted copy` files;
   the hook skips a file whose content differs from what it last wrote and reports it, rather than
   fighting a sync service.
4. **28 MB of docs is not a vault.** Curated and gated; the count of notes stays a person's handful plus
   one per app.
5. **The seed's leftovers.** `apps/obsidian/hooks/prepare` is untracked today and its volume name
   fallback is another project's — both are fixed by this item (committed, and the volume taken from
   the compose project, not a literal), and the fix is a diff a reader can check.
6. **Obsidian's `.obsidian/`** stays Obsidian's. Nothing here writes into it, and the plugins a person
   installs stay theirs.

---

## 5. The work, in slices (the plan is `apps/project-pln/plans/obsidian-vault.yaml`)

1. **vault-001 — research and this document** (done).
2. **vault-002 — the manifest and the gate**: `apps/obsidian/vault.yaml` + `vault-sources-lint.py`.
   Proof: the gate fails on a newly added `ai/context` doc and passes once it is declared.
3. **vault-003 — the compiler**: `render_vault()` → `.generated/vault/`, deterministic, with the
   manifest. Proof: two renders are byte-identical; a changed source changes exactly one note.
4. **vault-004 — the sync**: `hooks/prepare` (committed) + `./bbox obsidian sync`, write-only-changed,
   never-delete, `stale: true`, and the hand-written folders seeded once.
5. **vault-005 — the mount and the three channels** (§3.5), including the `AGENT.md` lines and the
   `SessionStart` line.
6. **vault-006 — the client boundary** (§3.6): the scope test, the printed exclusion list, and a test
   that a client-scoped render contains no herd note and no `.env` value.
7. **vault-007 — retire `ai/obsidian`** from the seed (keep the two useful notes as `ai/context` docs if
   the owner wants them), so no office inherits another deployment's brain.

---

## 6. Recommendation, in one paragraph (Hebrew, for the item)

מומלץ **לקמפל את הכספת ולא לשלוח "כספת התחלה" כתובה ביד**. מה שקיים היום הוא בדיוק הבעיה: `ai/obsidian`
הוא המוח של *פריסה אחרת* מלפני חמישה חודשים («digital-office», עם `Chess Game.md` ו-`Night Report`
שלה), וה-hook שמעתיק אותו (`apps/obsidian/hooks/prepare`) **אינו בכלל בריפו** (uncommitted) — הוא רץ רק ב-checkout הזה,
עם שם volume של פרויקט אחר. מה שכן קיים הוא התבנית הנכונה: `render_agent_context` כבר מקמפל את הבריף של
כל אפליקציה מותקנת לקובץ אחד שהסוכן קורא בכל סשן (1,457 שורות), ומכיוון ש-`ai/context` הוא 151 קבצים
ו-28MB — אין בכלל אפשרות "לשקף", אלא רק לפרסם תת-קבוצה מוצהרת. לכן: מניפסט אחד
(`apps/obsidian/vault.yaml`), צעד קומפילציה (`render_vault` → `.generated/vault/`), סינכרון שכותב רק את
מה שהשתנה ולעולם לא מוחק, ושער שנכשל כשמסמך חדש ב-`ai/context` לא הוצהר — כך «זה נשאר מעודכן» מפסיק
להיות הבטחה. הסוכן מקבל את הכספת בשלושה ערוצים בלי לגעת בקובץ כניסה: שלוש שורות ב-`AGENTS.md` של
האפליקציה (שכבר נטענות לכל סשן), mount של `/workspace/vault` ל-`bina-claude`/`bina-ds`, ושורה אחת
מה-hook הקיים של `SessionStart` ב-Claude Code. ולשכה של לקוח מקבלת **רק את עצמה**: כל מה שנוגע לעדר —
`dgo-herd.md`, `dgo-security.md`, `herd.yaml` — מסומן `scope: herd` ומרונדר רק כשמזהה הלשכה נמצא בעדר
(נמדד: `DGO_OFFICE_ID=hp-laptop`), וברירת המחדל היא לא; בלי סודות, בלי נתוני לקוח אחר, ובלי המוח של
פריסה אחרת.
