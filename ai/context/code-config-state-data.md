# Code, config, platform state and data — the proposed line (DGO-361)

§8 of [dgo-architecture-2026.md](dgo-architecture-2026.md), kept in its own file; its subsections keep the §8.x
numbers the architecture review points at.

The owner, 2026-08-27: «we must learn the best practices and draw a clear line between code / config /
platform state / data». This section proposes that line, so that a client's repository holds the whole business
solution and nothing else.

**Status: a proposal (2026-11-10).** What exists today is said so, with its file. Everything else is proposed,
and §8.6 lists each change as a step. Three points change a standing rule or an open decision of the owner's,
and §8.7 records them as his to decide; nothing here acts on them first.

It would replace the table in [platform-operating.md §"Where state lives"](platform-operating.md) (line 62; the
row that says `platform.state.yaml` is "in git: yes" is line 69). It refines §2.3's row on the state file: the
business's **declaration** would go into git, and the platform's **record** into the office's data directory.

The test for the line: delete the checkout and clone it again, and the office loses nothing. Or, in
12-factor's words, the code could be published at any moment without leaking anything
([12factor.net/config](https://12factor.net/config)). `scripts/release/public-export.py` runs that test
on every release. Today it passes only because `scripts/release/public/exclude.txt` holds back what the
tree should never have carried.

### 8.1 Prior art

| Product | Code | Config | Its own state | User data | The lesson for DGO |
|---|---|---|---|---|---|
| **Claude Code** | `~/.local/bin/claude` → `~/.local/share/claude/versions/<v>`. It updates itself and keeps the two newest versions ([setup](https://code.claude.com/docs/en/setup)) | `~/.claude/settings.json` (user); `.claude/settings.json` (project, committed); `.claude/settings.local.json` (project, personal, kept out of git); managed settings above all, in a documented precedence stack ([settings](https://code.claude.com/docs/en/settings)) | `~/.claude.json` (account, trust, per-project state, written by the program itself); transcripts and memory in `~/.claude/projects/<p>/`. `CLAUDE_CONFIG_DIR` moves all of it ([.claude directory](https://code.claude.com/docs/en/claude-directory)) | the project | The shared declaration is committed. Personal overrides and the program's own state go in separate files that git never sees. One variable moves the whole home. |
| **Docker Desktop** | the app bundle (`/Applications/Docker.app`; known, not re-fetched) | `settings-store.json`: Mac `~/Library/Group Containers/group.com.docker/`, Windows `%APPDATA%\Docker\`, Linux `~/.docker/desktop/` ([settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/)); CLI config in `~/.docker/config.json` (known) | images and containers, inside one VM disk: Mac `~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw` ([Mac FAQ](https://docs.docker.com/desktop/troubleshoot-and-support/faqs/macfaqs/)); on Windows a WSL 2 distro's vhdx (path unverified) | volumes, which outlive any container ([volumes](https://docs.docker.com/engine/storage/volumes/)), on the same disk | Volumes are the data boundary. Hiding them in one opaque disk is what makes "uninstall destroys data" and "15 GB left behind" (packaging/macos.md:231-236, packaging/windows.md:164-173). |
| **gcloud** | the SDK install directory, with installation-wide properties (known, not re-fetched) | **named configurations** in `~/.config/gcloud` (Windows `%APPDATA%\gcloud`). One is active; a command picks another with `--configuration` or `CLOUDSDK_ACTIVE_CONFIG_NAME`; `CLOUDSDK_CONFIG` moves the directory ([configurations](https://docs.cloud.google.com/sdk/docs/configurations)) | credentials and tokens in the same directory, e.g. `application_default_credentials.json` ([ADC](https://docs.cloud.google.com/docs/authentication/application-default-credentials)) | in the cloud | One named configuration per target, chosen explicitly and kept outside the project. |
| **n8n** | the package or image | environment variables, with a `_FILE` suffix for secrets ([config methods](https://docs.n8n.io/hosting/configuration/configuration-methods/)); `N8N_USER_FOLDER` | the encryption key, generated on first launch into `~/.n8n` ([encryption key](https://docs.n8n.io/hosting/configuration/configuration-examples/encryption-key/)); SQLite there by default | workflows, credentials (encrypted with that key) and executions, all in the database. JSON export/import ([CLI](https://docs.n8n.io/hosting/cli-commands/)); source control pushes workflows, tags and credential/variable **stubs**, never values ([git](https://docs.n8n.io/source-control-environments/understand/git/)) | What the running system holds as data can be code in git. Secrets travel as stubs. The decrypting key lives outside git and must be backed up. |

### 8.2 The DGO line

| Class | What | Where (per office) | Writer | In a client fork? |
|---|---|---|---|---|
| **Code** | `platform/`, `platform-base/`, `apps/<id>/` (manifest, compose, hooks, `blueprint/n8n/*.workflow.ts`, per n8n-development.md:12-14), `packaging/`, `scripts/`, `bbox`, `bbox.cmd`, `AGENTS.md`, `.claude/{settings.json,hooks,skills}`, agent presets (`apps/bina-ds/harness/profile/`) | the checkout at a commit | commits. The target is that an office runs committed code only (§2.3); **today** `bbox run --build` builds the working tree, uncommitted edits included (§8.6 item 12) | **yes**: the public tree, plus the client's own `apps/<id>/`. The public export is scrubbed and holds back all of `.claude/` (scripts/release/public/exclude.txt:49), so a fork has neither our skills nor the office-branch guard |
| **Product default** | `platform.state.default.yaml`, `platform.state.core.yaml` (no `state:`/`by:`/`remote:`, per the file's header) | the checkout | upstream only | yes, from upstream; never edited in a fork |
| **Business declaration** (config the business declares) | per office: the app dispositions, `bindings:`, the non-secret fields of `instances:`, `office:` identity, the compose project name, and the few non-secret env keys (`BUSINESS_NAME` and the domain; .env.ex:1-16 says everything else derives) | **`offices/<office>.yaml`** (proposed; no such directory today) | a person or agent, by commit; a console change would reach it only through `bbox state export` (proposed, 8.3; no such verb today) | **yes**, one file per office of the business |
| **Secrets** | `.env` (gitignored, mode 600); the `connections` vault (volume `connections_vault`, platform-base/connections/docker-compose.yml:65); `N8N_ENCRYPTION_KEY`; link private keys (issues/network-state-holds-a-private-key-and-nothing-backs-it-up.yaml) | the machine, and data volumes | onboarding, the console, the vault | **never**. `.env.ex` (the template) comes from upstream |
| **Platform state** (the runtime record) | the console's dispositions with `by:`, the link's `remote:` view of peers (addresses, `fetched:`), the `serve:` that converge writes, generations, locks, other offices' declarations held by dgo-extend (`/data/dgo/<id>.yaml`, apps/dgo-extend/app.py:16), installer memory | **`${DGO_DATA}/state/`** (proposed) and app volumes; **today** `platform.state.yaml` in the checkout | the platform only, through the compiler's writers under a lock (reconcile.py:419-432; G33) | **never** |
| **Business data** | docker volumes `<project>_*`: postgres, n8n's database with its executions, drive, mail, INDOX storage, Plane, sessions | the engine's disk (8.5) | the apps | **never**; backed up off the server (apps/dgo-extend/converge.py `step_backup`/`step_offsite`) |
| **Compiled artefacts** | `.generated/` (compose, registries, routes) | the checkout, gitignored | `bbox`/`dgo render` | never; delete it and it is rebuilt |
| **Agent/session state** | transcripts, memory, work-left notes, local permission grants; office agents' homes (volume `bina_ds_home`); Claude Code's `~/.claude` | agent volumes, or the machine's `~/.claude` | the agents | **never**. Agent *definitions* are code (row 1) |

### 8.3 Precedence and the one writer (proposed; none of this exists yet)

What an office runs would be three layers, the later one winning per key, like Claude Code's
`settings.json` under `settings.local.json`:

1. the **product default**, only when the office has no declaration (today's `ensure_state`,
   reconcile.py:787-835);
2. the office's **declaration** (`offices/<office>.yaml`, in git);
3. the **record** (`${DGO_DATA}/state/`): what this office changed since its last export, each change
   with `by:` and the hash of the declaration it was made against.

The console and `bbox apps` would write only to the record, so §2.1's "one writer per state block" holds.
When a pull changes a declared value that the record overrides, the apps screen would show the conflict;
the resolver never settles it by position (the refusing resolver, §2.1). `bbox state export` would write
the record's dispositions into the declaration for a commit and clear them from the record: n8n's
source-control push applied to the app set. A converge of a declared office (dgo-extend `step_code` +
`step_state`) would then be: check out the fork at a commit, and drop the overrides the declaration
contradicts. Today `git checkout` does touch the office's state file (converge.py:1078 and :1701).

### 8.4 A client fork (proposed; §8.7 holds the owner's decisions it needs)

- **Its upstream would be the public repository** `bina-solution/digital-office`, never our private one. The
  public `main` takes one commit per release, as a fast-forward that is never forced
  (scripts/release/public/README.md, "Publish"). Our private tree carries other clients' apps
  (`apps/chimney-services/`), our plans, issues and open security findings, all held back by
  `exclude.txt`. A fork of the private tree would carry all of them. The public copy is scrubbed and shares no
  history with ours (public/README.md:3-4), and it holds back `.claude/`, so a client's fork has no
  office-branch guard and none of our skills.
- **It holds**:
  - upstream's tree, unchanged;
  - the client's own apps as `apps/<id>/` (layer 3: the directory is the layer, reconcile.py:36-45);
  - their automations in `apps/<id>/blueprint/n8n/`;
  - one `offices/<office>.yaml` per office of the business;
  - optionally, the client's own skills or agent presets.
- **It would take upstream by merging a release tag** (`git fetch upstream && git merge v0.N.0`), never
  by a hand patch. **Today the public repository has no release tags** (`git ls-remote`: `refs/heads/main` and
  one arm64 pre-release tag), and Publish commits a snapshot without tagging (public/README.md:36-38), so a tag
  step comes first (§8.6). Upstream never writes `offices/` or a client's `apps/<id>`, and a fork never edits
  an upstream path, so a take merges clean; a gate (proposed, §8.6 item 11) would hold both sides.
- **How a client's proven work comes back is the owner's decision (§8.7).** AGENTS.md Non-negotiable 6 merges
  proven work into `dgo-stable`. A client forked from the public repository cannot open a pull request against
  our private repository, and the two share no history.
- **One line for all its offices**, a file per office rather than a branch, would take client offices out of
  the office-branch rule (AGENTS.md Non-negotiable 6, a security rule, S8). Today client offices are branches
  of the private repository (`origin/exw-vps-dgo`, `exw-wtablet-dgo`, `willi-dgo`; last committed
  2026-09-30 to 2026-10-11). That too is the owner's (§8.7). Our own herd keeps the branch rule either way.
- **Never in it**: `.env`, the vault, volumes, `.generated/`, `data/`, `${DGO_DATA}`, sessions,
  decrypted credentials, and encrypted n8n credential exports too. The .gitignore comment allows the
  encrypted exports, but every reader of a fork holds them: exposure is "bounded to repo readers plus
  any fork" (platform-os-release-plan.md:503).

### 8.5 Install, per OS

| OS | From source (real today) | The engine, and where business data lives | The `dgo` binary |
|---|---|---|---|
| **Windows** | `git clone` anywhere on `C:`, then `bbox.cmd run` (running-on-wsl.md:1-12). It hands off to the WSL distro `Ubuntu` (bbox.cmd:31,59) | Docker CE 28.x inside that distro. Volumes are in its `ext4.vhdx`, and `wsl --unregister` destroys them (packaging/windows.md:170-173). **Planned**: an Inno Setup installer with its own `BinaOS` distro via `wsl --import` (packaging/windows/BinaOS.iss, windows.md:10-22). | `dgo.exe` answers the compiler's verbs natively; everything else goes through `bbox.cmd` (packaging/dgo/README.md) |
| **macOS** | `./bbox run` in a clone under `$HOME` | a Lima/vz Ubuntu guest with Docker CE 28.5.2, everything under `~/.bbox/macos` (LIMA_HOME and the VM disk; packaging/macos/engine.sh:24-35). The checkout is mounted at the same path; the edge is on `:8080` (packaging/macos.md:3-22). **Planned**: a signed `.app` whose disk sits under `~/Library/Application Support/<bundle-id>/`, with an in-app uninstall (macos.md:178, 231-236) | as on Linux |
| **Linux / VPS** | `debian-install.sh` (git and Docker), then clone and `./bbox run`. Docker 28.x runs under systemd (running-the-stack.md, table); containers restart through `restart: unless-stopped`. After a boot dgo-link and dgo-carry, which share dgo-net's network, do not come back with the engine, and the step that would restart them runs only inside `bbox up` (measured on the HP, issues/after-a-reboot-the-door-and-the-carrier-stay-down-until-someone-runs-bbox.yaml); no unit runs that step | `/var/lib/docker/volumes`. **Built once, used by no live office** (packaging/ROADMAP.md:7-15, the BinaOS r5 bundle): `/opt/binaos` program, `/etc/binaos` config, named volumes as data, and the `binaos.service` oneshot (packaging/linux.md:134-152; packaging/linux/binaos.service) | from source: `go build` in `packaging/dgo`. Release: `packaging/build-binaries.sh`, run on a `v*` tag by `.github/workflows/release-binaries.yml` |

**What is real and what is planned for the binary path.**

- **Real**: the installer stub verifies a signed chain, installs the core to `~/.dgo/core`
  (packaging/installer/main.go:395-400), and remembers versions in
  `<user config dir>/dgo/install-state` (main.go:373-381).
- **Not live, reason 1**: `packaging/installer/roots.txt` names no root, so every stub is a development
  build that installs nothing (installer/README.md, "Fail-closed").
- **Not live, reason 2**: `dgo` refuses to run outside a checkout (`findRoot`,
  packaging/dgo/main.go:148-163), except for `--version` and `be-child` (main.go:98-120).
- **Planned**: "download → wizard, no git clone" is step 7 of core-native-plan.md.

**Proposed directories** (none exists today; today's names are `/opt/binaos`, `/etc/binaos`, `~/.dgo/core` and
`~/.bbox/macos`). One variable, `DGO_DATA`, would move all of them, as `CLAUDE_CONFIG_DIR` and
`CLOUDSDK_CONFIG` do. The defaults would be the same from source and from the binary, so the checkout stays
pure code.

| | Program | Secrets (`office.env`) | Record and data |
|---|---|---|---|
| Linux server (root) | the checkout, or `/opt/dgo/<version>/` | `/etc/dgo/<office>.env` | `/var/lib/dgo/<office>/` and the engine's volumes |
| macOS | the checkout, or `~/.dgo/core/<version>/` | `~/Library/Application Support/DGO/<office>/` | the same directory; the engine disk moves from `~/.bbox/macos` to `…/DGO/engine/` with the `.app` |
| Windows | the checkout on `C:`, or `%LOCALAPPDATA%\DGO\core\<version>\` | inside the distro: `/etc/dgo/` | inside the distro: `/var/lib/dgo/<office>/`, next to the volumes. The engine reaches a Windows-side path only through the mount |

### 8.6 What changes

1. `platform.state.yaml` is still tracked on every office branch (mac, hp, vps1, dell, claude, exw-vps,
   exw-wtablet, willi) and on `dgo-stable`, not on `main`. dgo-stable's last change to it is db1d1995
   (2026-10-22, the dell-dgo merge): the Dell's copy plus six lines the merge added. Untracking it and naming it
   in `.gitignore` is the owner's open decision on
   issues/one-offices-desired-state-is-what-every-clone-starts-from.yaml (§8.7); `ensure_state`'s ORIG_HEAD
   restore (reconcile.py:787-835) already handles the pull that untracks it.
2. Split the file: the declaration goes to `offices/<office>.yaml`, and the record (with `by:`, and
   `remote:` with its addresses and `fetched:`) goes to `${DGO_DATA}/state/`. This touches the readers
   and writers in platform/manager/reconcile.py (`STATE`, :46) and its Go twin
   packaging/dgo/internal/compiler/writers.go. 134 tracked files name the path, not counting `*.md` and
   `issues/` (216 with them).
3. Add one data root, `DGO_DATA`, to scripts/lib.sh and reconcile.py. Move into it the state lock
   (`data/.locks`, reconcile.py:419) and every bind mount into the checkout:
   - `../../data/power` (platform-base/machine/docker-compose.yml:48);
   - `data/lan` and a second `data/power` (apps/dashboard/docker-compose.yml:59, :62);
   - `data/browser42` (apps/browser42/docker-compose.yml);
   - `${BBOX_REPO_HOST}/.dgo/doors` (apps/dgo-extend/docker-compose.yml:293, written by converge.py:3744-3752);
   - apitools' document storage and logs, `./storage` and `./logs` (apps/apitools/docker-compose.yml:89-90).
4. Move generations from `.generated/generations` (reconcile.py:2265) to `${DGO_DATA}/generations`.
   They are rollback state, and platform-operating.md:94 calls `.generated/` deletable output.
5. Pin each office's compose project name in its declaration. The volume names follow the checkout's
   directory name unless pinned (scripts/lib.sh:390-398), so a re-clone elsewhere orphans the data.
6. Mark every key in `.env.ex` (278 keys at 2026-11-10; 54 named SECRET, PASSWORD, TOKEN or KEY, 61 with PASS and
   PRIVATE) as declared, secret or machine, and
   move the declared ones into `offices/<office>.yaml`, so that `.env` holds secrets and machine values
   only.
7. Let dgo-extend read the declarations of the offices it manages from the fork's `offices/`, not only
   from its own volume (`/data/dgo/<id>.yaml`, apps/dgo-extend/app.py:16), so that a client's herd is in
   its repository.
8. Untrack agent session state and keep it in agent data: `.claude/settings.local.json` (Claude Code's
   own docs keep it out of git), `.claude/launch.json` (this machine's), `.claude/WORKLEFT.md`,
   `.claude/from-azaria.md`, `.claude/needs-azaria.md`, `.claude/first-message.txt` and `ai/obsidian/`
   (28 files). This is an entry-file-adjacent change, so it goes as its own item.
9. After the owner's decision (§8.7): add a tag step to Publish (scripts/release/public/README.md:36-38), then
   move each client office to a fork of the public repository that merges those tags. Today Exampleu takes
   upstream by hand patches (a `git apply` of 157930e7's six runtime files; the Mac's
   ci-artifacts/exampleu-start/ notes, :87 and dgo1594-exampleu-live.md:3), and client offices are branches of
   our private repository (`origin/exw-vps-dgo`, `origin/exw-wtablet-dgo`, `origin/willi-dgo`, all stale).
10. Move each client's app out of our private tree into that client's fork (`apps/chimney-services/`,
    held back by scripts/release/public/exclude.txt).
11. Add a gate that refuses a client path in upstream and an upstream path edited in a fork. Teach G9
    (scripts/refactor/layering-lint.py) that `offices/` is a declaration directory, not a layer.
12. Make `bbox run` refuse to build or run a dirty tree outside an explicit development mode (§2.3).
    On mac-dgo on 2026-11-10, `git status` showed about 40 modified tracked files (43 at 08:10 local) and 64
    untracked, and `bbox run --build` would ship them.
13. Ship the catalog with the binary (packaging/dgo/main.go:148-163), and hold the root key ceremony so
    that `roots.txt` names a root (packaging/installer/roots.txt). The ceremony is a `בעלים` item.
14. Keep the core's versions side by side with a current pointer, not one slot at `~/.dgo/core`
    (packaging/installer/main.go:395), so that a bad core rolls back without a download.
15. Install a `dgo.service` for a from-source server office, from packaging/linux/binaos.service, and
    rename `binaos` to `dgo` there and in packaging/linux.md:143-146.
16. Once the owner has decided §8.7, rewrite platform-operating.md §"Where state lives" (line 62) to the line
    decided.

### 8.7 What only the owner decides (recorded, not waited on: the steps above that do not depend on them go on)

1. **Untracking `platform.state.yaml`** (§8.6 item 1). It is already his open decision on
   issues/one-offices-desired-state-is-what-every-clone-starts-from.yaml.
2. **Client offices as forks of the public repository**, one line per business with a file per office (§8.4). This
   takes client offices out of the office-branch rule, which AGENTS.md calls a security rule (Non-negotiable 6,
   S8), and out of reach of its guard, since the public export holds back `.claude/`.
3. **How a client's proven work comes back.** AGENTS.md has proven work merged into `dgo-stable`; a public fork
   shares no history with our private line and cannot open a pull request against it.
