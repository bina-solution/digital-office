# Operating `obsidian`

The office's vault, served inside the office. This app runs **Ignis** (`nobbe/ignis`, pinned in
`docker-compose.yml`): a shim implementing the Electron APIs Obsidian calls, so the **real** Obsidian
— downloaded from its official source on first start, never redistributed here — runs on this server
and is served to the browser. The tile is at `/a/obsidian/`; the app also answers on `obsidian.<domain>`.

## What you can and cannot do from here

- **The vault is one folder** — `${OBSIDIAN_VAULT_HOST}` when the office names an absolute host folder
  (an owner's synced vault on a laptop), else the named volume **`obsidian_vault`** (a server office:
  that volume is the vault). It is mounted as the single vault `/vaults/vault`. There is exactly ONE
  copy. Never create a second copy of the vault and never "helpfully" export one. The office agent does
  not mount the vault on this line yet (bina-ds has no `/workspace/vault` here; WBC's branch has it,
  and porting it is cyc-272 item 7). Reach it through this app's container instead:
  `./scripts/dc exec -T obsidian ls /vaults/vault`, `./scripts/dc exec -T obsidian cat "/vaults/vault/<note>.md"`,
  and to write one `./scripts/dc exec -T obsidian sh -c 'cat > "/vaults/vault/<note>.md"' < <file>`.
- **The notes are the owner's, except `Operatives/`.** `00 Start here.md` is the map of the company's notes: how
  tasks (Plane), the office browser and every app are used. `Operatives/` is the collective memory of the
  office's recurring jobs (processing a meeting, Kadima, task management, a new app, a weather check with the
  browser, domains, websites, a security review…), and keeping it is the agent's job (the owner, DGO-1081):
  **before running an operative, read `Operatives/README.md` and the operative's own note and work by it; no
  note yet → write one from the README's template; after the run → add one line to its `Run log` and correct in
  place any step that proved wrong.** Short: steps and commands, never a story, never a secret. Any other note
  is changed only when the owner asks.
- **`.obsidian/` is Obsidian's own configuration** (community plugins, themes, `workspace.json`, hotkeys). The
  office's rule "never touch `.obsidian/`" is about the AGENT, and it stands: you do not edit files there,
  the app does.
- **`data.volumes`: `obsidian_vault`** (the vault, when no host folder is named), **`obsidian_state`**
  (`/app/data` — Ignis state: server plugins, sync configuration) and **`obsidian_app`**
  (`/app/obsidian-app` — the downloaded Obsidian + headless CLI, a cache). All three are named volumes
  and survive a recreate.

## The screens, and what each thing is

- `/` — the vault (opens `vault` automatically; several vaults would list in a manager).
- `?file=<path>` — opens a note directly; `?workspace=<name>` — a saved workspace. Useful links to
  hand the owner instead of describing a path.
- Plugin compatibility is a real boundary: plugins built on Obsidian's own API load; ones needing Node
  native modules or `child_process` do not. If a plugin the owner uses is missing, that is why — the
  answer is upstream compatibility, not a container tweak.

## Operating it

```bash
./scripts/dc ps obsidian                      # state of the one container
./scripts/dc logs --tail 100 obsidian         # the truth about a failed start
./scripts/dc restart obsidian                 # after a settings change
./scripts/dc up -d --no-deps --no-build obsidian
```

- **The first start downloads Obsidian** (`start_period: 180s`); a start that is "unhealthy" for the
  first minute or two is the download, not a fault. Read the log before calling it broken.
- **Memory.** Ignis serves the app and the files; Obsidian's UI runs in the visitor's browser. Measured
  on WBC's tablet: ~120 MiB at rest; the compose limit is 768M. On a small machine, look at the heavy
  apps first — never switch off the vault the owner opens by hand.
- Updating Ignis is a decision: bump the pinned tag in `docker-compose.yml`, then
  `./scripts/dc up -d --no-deps --no-build obsidian`. Never `latest`.

## Traps

- **Two writers, one file** (a host folder that a sync service also writes, such as OneDrive). Editing
  from a phone and from here at the same moment produces a `conflicted copy` file — that is the sync
  service, not a bug here. Warn the owner rather than "fixing" it by deleting a file.
- **An empty vault.** On a server office's first start the named volume is empty: that is a new vault,
  not a fault — never set `OBSIDIAN_VAULT_HOST` to "fix" it. Where a host folder IS named, a path that
  does not exist is created as an empty directory: check the path in `.env` first.
- **`OBSIDIAN_VAULT_HOST` is an absolute path or nothing.** A bare name becomes an undeclared volume and
  the project stops loading; a `:` in the path breaks the mount; `./x` lands inside the checkout.
- The container has **no authentication of its own** (the edge does that). Never publish its port on the
  host, and never reach it from outside the office network.
- `auth: sso` means the SSO blueprint for this host must exist; after enabling the app,
  `python3 platform/manager/reconcile.py render` and a console restart are what put the tile back in the
  rail (see `office-operations`).
