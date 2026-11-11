# Operating `obsidian`

The office's vault, served inside the office: **Ignis** (`nobbe/ignis`, pinned in `docker-compose.yml`) shims
the Electron APIs, so the **real** Obsidian — downloaded from its official source on first start, never
redistributed — runs here and is served to the browser. Tile `/a/obsidian/`; host `obsidian.<domain>`.

## What you can and cannot do from here

- **The vault is at `/workspace/vault`** (DGO-1642), mounted read-write into `bina-ds` and `bina-claude`.
  **Read it first in a session:** `00 - START HERE.md` is this office's compiled map; then `Apps/<app>.md`.
- **A note with `generated: true` is the compiler's.** To change it, change its SOURCE (`vault.yaml` says
  which) and run `./bbox obsidian sync`. An edit to a generated note is kept, never overwritten, and
  reported `skip-edited` — it is not the truth.
- **The notes are the owner's, except `Operatives/`.** `Notes/`, `Projects/`, `Sessions/`, `Memory/`,
  `_Hooks/` are his. `Operatives/` is the office's memory of its recurring jobs, and keeping it is yours
  (DGO-1081): before an operative, read `Operatives/README.md` and its note and work by it; no note → write
  one from the template; after the run → one line in its `Run log`, and fix a step that proved wrong.
  Steps and commands, never a story, never a secret.
- **One folder, one copy.** `${OBSIDIAN_VAULT_HOST}` when the office names an absolute host folder, else
  the named volume `obsidian_vault`. Ignis serves it as `/vaults/vault`. Never make a second copy. Mount
  missing → through the container: `./scripts/dc exec -T obsidian ls /vaults/vault`.
- **`.obsidian/` is Obsidian's configuration**: the agent never edits it; the app does.
- **`data.volumes`**: `obsidian_vault` (the vault), `obsidian_state` (`/app/data`, Ignis state),
  `obsidian_app` (`/app/obsidian-app`, the downloaded app, a cache). All survive a recreate.

## The screens

`/` opens the vault; `?file=<path>` opens a note, `?workspace=<name>` a workspace — hand the owner a link,
not a path. Plugins on Obsidian's own API load; ones needing Node native modules or `child_process` do
not (an upstream limit, not a container tweak).

## Operating it

```bash
./bbox obsidian sync                    # compile the vault and carry what changed into it
./bbox obsidian sync --no-render        # the same, without re-running the compiler
./scripts/dc logs --tail 100 obsidian   # the truth about a failed start
./scripts/dc up -d --no-deps --no-build obsidian
```

## How the vault is filled (DGO-1642)

Compiled, never kept by hand:
- **declaration** `apps/obsidian/vault.yaml`: `notes:` (verbatim `ai/context` docs), `herd_docs:` (the
  business's offices), `generated:` (index, inventory, one note per installed app, diagrams), `excluded:`
  (each with a `why`);
- **compiler** `reconcile.render_vault()` → `.generated/vault/` on every `bbox run`, deterministic;
- **carrier** `apps/obsidian/vault-sync.sh` (`hooks/prepare`, `bbox obsidian sync`): writes only what
  changed, never overwrites a person's edit, never deletes (a gone source is listed in `.office/stale.txt`);
- **gate** G112 `vault-sources-lint`: every `ai/context/**/*.md` is declared or excluded BY NAME.

Publish a doc: add it to `notes:` and sync. Keep one out: `excluded:` with a reason.

**A client's vault.** `herd_docs:` (the herd's machines, addresses and findings: `dgo-herd.md`,
`dgo-security.md`, `herd-from-anywhere.md`, `take-the-lead.md`, the owner guide, `moving-an-office.md`)
render **only** where `DGO_OFFICE_ID` is one of `apps/computers/herd.yaml`'s `offices:` — anything else
fails closed. No `.env` value reaches a note; no other app's data is read. An app's own brief
(`Apps/<app>.md`) may name the herd's offices as examples: it is that app's text, the same everywhere.

- **The first start downloads Obsidian** (`start_period: 180s`): a minute or two of «unhealthy» is that.
- **Memory**: ~120 MiB at rest (measured on EXW's tablet), limit 768M; the UI runs in the browser. Never
  switch off the vault the owner opens by hand to save memory.
- Updating Ignis is a decision: bump the pinned tag, then the `up` above. Never `latest`.

## Traps

- **Two writers, one file** (a synced host folder, e.g. OneDrive): a `conflicted copy` is the sync
  service's. Warn the owner; never delete a file to «fix» it.
- **An empty vault** on a server's first start is a new vault, not a fault — never set
  `OBSIDIAN_VAULT_HOST` to fix it. A named host path that does not exist is created empty: check `.env`.
- **`OBSIDIAN_VAULT_HOST` is an absolute path or nothing**: a bare name is an undeclared volume, a `:`
  breaks the mount, `./x` lands in the checkout.
- **No authentication of its own** (the edge does it): never publish its port, never reach it from outside.
- `auth: sso` needs its SSO blueprint: after enabling, `reconcile.py render` and a console restart put
  the tile back.
