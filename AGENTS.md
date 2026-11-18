# AGENTS.md — for coding agents and contributors

Read this first if you are an AI coding agent (Claude Code, Codex, Cursor, any other) or a person about to change
this repository. It is short on purpose: everything else is read when a task needs it.

## What this is

DGO — the digital office — runs a business's office on a machine of its own: mail, documents and their automations,
meetings, a project board, a drive, chat, and an AI agent that works inside the office. Every app is a container, the
whole set is compiled from declarations, and one command brings it up. The screens are Hebrew-first and right-to-left;
`./bbox lang en` switches an office to English.

## First run

```sh
./debian-install.sh          # Docker and its compose plugin, and a .env from .env.ex (DGO_LOCAL=1: a local office)
./bbox run                   # compile the office, then bring it up — on Windows: bbox.cmd run, on a Mac: the same
```

Then open `http://console.localhost`. `./bbox help` lists every command.

## Ask the running office, not the repository

Facts about an installation — its offices, the machines they run on, the links between them, which app runs where —
are read live from that office. **A change adds no installation fact to this repository**: if a task needs one, run
the command.

| You want | Run |
|---|---|
| every command | `./bbox help` |
| this office: what runs, what is off, what drifted | `./bbox status` |
| **what this office, or one app, is and does now**: each app's brief, commands, addresses and state | `./bbox context [app]` |
| **the whole network as it is now**: every office, its link, what runs where, whether it takes updates | `./bbox computers map` (the `computers` app) |
| the links between offices, as measured now | `./bbox dgo link status` (the `dgo-extend` app) |
| the apps a linked office publishes to this one | `./bbox remote` |
| every office against the herd you declared, and what should move | `./bbox computers herd` (the declaration is `apps/computers/herd.yaml`) |

`dgo-extend` and `computers` are off in a new office: `./bbox apps enable dgo-extend computers`, then link a second
office from the console.

## Layout: the directory is the layer

- `platform/` — the compiler. `platform/manager/reconcile.py` reads every `apps/*/app.json` and the office's own
  choices in `platform.state.yaml` (made from `platform.state.default.yaml` on the first run), and renders
  `.generated/` — never edited or committed by hand. Its native Go successor is `packaging/dgo`.
- `platform-base/` — the core every office gets: the edge (Traefik), sign-in (authentik), Postgres, Redis, the
  console, the app manager, the credential vault (`connections`), notifications, security.
- `apps/` — one folder per app, chosen per office: its `app.json` manifest, its compose file when it runs a service,
  and its `AGENT.md` brief. An app never reaches into another app's folder.
- `scripts/` — `dc` (compose over the compiled files), `lib.sh`, and `refactor/` (the gates).
- `docs/`, `ai/context/` — product documentation and the design notes behind it.

## Rules every change keeps

Code comments cite these by number («AGENTS.md rule 8»).

1. **Never run `docker compose` directly.** The services are compiled into `.generated/`, so a bare
   `docker compose up` resolves nothing and exits 0. Use `./bbox`, or `./scripts/dc` for compose itself.
2. **Declarations, not scripts.** A service, route or setting goes into an app's `app.json` or compose file and is
   compiled; it is never patched into `.generated/` or into a running container.
3. **Pass the gates.** `python3 scripts/refactor/run-gates.py --all`; what each gate scans, and the few marked
   KNOWN FAILING, is in [scripts/refactor/GATES.md](scripts/refactor/GATES.md).
4. **One example first, and proof from real output.** Make one case work and read it before changing the rest; a
   change is done when its real output says so, not when it should work. Back up data before anything destroys it.
5. **Language.** Code, commit messages and docs are in English; the screens speak the office's language. Only
   `platform-base/bina-ui/theme-tokens.css` names a colour; screens use its tokens.
6. **An office runs from its own branch.** `DGO_BRANCH` in an office's `.env` names the git branch it runs and commits
   on; `scripts/lib.sh` (`office_branch_admit`) and `scripts/git-hooks/` hold it. A contribution to this repository
   is a pull request.
7. **Fix the root, minimally.** Never change a test or a doc to make something pass; a test that changes is said
   apart from the fix.
8. **Tightening a contract? Find every caller mechanically first** — with a gate, or a search whose file count you
   show — and prove it finds the callers before the fix and none after it.

## Where to read next

| Need | Read |
|---|---|
| run, build and test the stack | [ai/context/running-the-stack.md](ai/context/running-the-stack.md) |
| write your first app | [ai/context/build-your-first-app.md](ai/context/build-your-first-app.md) |
| the CLI/API standard every app follows | [ai/context/app-cli-api-standard.md](ai/context/app-cli-api-standard.md) |
| Windows (WSL) and macOS | [ai/context/running-on-wsl.md](ai/context/running-on-wsl.md), [packaging/macos.md](packaging/macos.md) |
| the index of the design notes | [ai/context/README.md](ai/context/README.md) |
| an app's own brief | `apps/<app>/AGENT.md`, or live with its commands and state: `./bbox context <app>` |
| the licence | [LICENSE](LICENSE) (AGPL-3.0) and [NOTICE.md](NOTICE.md) |
