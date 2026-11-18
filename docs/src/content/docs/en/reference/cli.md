---
title: The command line
description: Every command of bbox, the office's command, by subject.
---

## Summary

```bash
./bbox <command> [arguments]
./bbox <app> <verb> [arguments]
./bbox help
```

On Windows: `bbox.cmd` instead of `./bbox`. Without a command, `bbox` shows the help.

The `--force` flag is accepted by every command, and skips the confirmation question.

## The life cycle

| Command | What it does |
|---|---|
| `bbox run [svc...]` | Brings the office up, or only the services named. |
| `bbox stop` | Takes the office down. The containers come down, the data is kept. |
| `bbox reset [--force]` | **Deletes all the data.** Asks first. |
| `bbox status` | A snapshot: containers, automations and permissions. |
| `bbox context [app] [--json]` | What the office, or one app, is and does now: each app's brief, commands and state, read live. |
| `bbox computers map [--json]` | The whole network of offices as it is now: every office, its computer, the link to it and what runs there. Read live, not from a file in the repository. |
| `bbox verify [dependencies]` | A readiness check. Exits with a non-zero code when something is broken. |
| `bbox logs [svc] [-f]` | The logs of every service or of one. `-f` keeps following. |
| `bbox update <app…>` | Deploys a rebuilt app, waits for it to be healthy, and goes back if not. |
| `bbox follow [--dry-run\|heal\|status\|install]` | The office updates itself from the branch in `DGO_FOLLOW`. |
| `bbox agent <verb>` | The office's agent from the terminal. `bbox agent --help` shows everything. |
| `bbox remote [office [alias [path]]]` | The apps of a linked office. |
| `bbox via <office> <bbox args…>` | Runs a `bbox` command on a linked office. |
| `bbox dialable [-Check\|-Undo]` | Whether another office can call this office. |
| `bbox secrets check` | Keys in `.env` that are empty or still hold a value from a template. Names only. |
| `bbox secrets plan [KEY…]` | How to replace each such key, and who reads it. Writes nothing. |
| `bbox rename-address [--dry-run] <old-domain> <new-domain>` | The office moved to another domain: the people's addresses move with it. |

## Moving to another computer

| Command | What it does |
|---|---|
| `bbox export [--mode full\|config] [--quiesce] [--out DIR]` | Keeps everything that is not in the folder: databases, automations, documents, users. By default: `exports/`. |
| `bbox import [DIR]` | Restores an archive into this folder. |

## The computer

| Command | What it does |
|---|---|
| `bbox apparmor [status\|validate\|verify\|install\|uninstall]` | Checks the computer's AppArmor. `install` requires `sudo`. |
| `bbox host-power [status\|install\|uninstall]` | A laptop that runs an office: does not sleep, does not overheat. `install` requires `sudo`. |
| `bbox baseline` | A check from zero: deletes, builds, brings up and checks. |
| `bbox ui-map` | Captures every screen into one picture. |
| `bbox flow-qa [suite…]` | Runs every flow and checks the result. |
| `bbox seed` | Fills in demo data, so every screen shows content. |

## Automations (n8n)

| Command | What it does |
|---|---|
| `bbox n8n pull <app> [wfId ...]` | From the live system to code. |
| `bbox n8n push <app> <wfId ...>` | From code to the live system. |
| `bbox n8n status` | What changed, what was published, which permissions. |
| `bbox n8n test <app> <wfId>` | Triggers and returns a result. |
| `bbox n8n verify` | Checks the permissions and returns links to reconnect. |

`bbox help` shows every n8n command.

## Apps and the catalogue

| Command | What it does |
|---|---|
| `bbox apps list\|validate` | The office's plan; checking the declarations. |
| `bbox apps enable\|disable <app>…` | Turns on or off. The data is always kept. |
| `bbox catalog keygen` | Creates a signing key for the office. |
| `bbox catalog build` | Builds a signed catalogue from `apps/`. |
| `bbox catalog verify [ref]` | Checks the signature and every entry. |
| `bbox catalog list [ref]` | The entries in the catalogue. |
| `bbox catalog show <id>` | What the app will do, before the install. |
| `bbox catalog trust <key-id> <hex>` | Trusts a publisher's key. |
| `bbox app install <ref>` | Installs by id, address or folder. `--dry-run` only shows. |

## Install

| Command | What it does |
|---|---|
| `bbox install debian` | `git` and Docker on Debian or Ubuntu. |
| `bbox install windows` | Preparing WSL. Run through `bbox.cmd`, not through Docker Desktop. |
| `bbox install macos` | The office's engine on a Mac, with no administrator rights. |
| `bbox engine <verb>` | macOS only: `start`, `stop`, `status`, `shell`, `socket`, `doctor`, `destroy`. |

## First run

| Command | What it does |
|---|---|
| `bbox onboarding` | Checks requirements, brings up, waits for everything to be healthy, and checks. In an office where n8n is off (as in a new office) it waits for it for about four minutes and ends with «n8n REST not ready yet»: there, check with `bbox status` and `bbox verify`. |
| `bbox onboarding --auth-state` | Only checks permissions and returns links to reconnect. |

## Each app's verbs

```bash
./bbox <app> <verb>
```

Every app with a `hooks/` folder has verbs of its own. `bbox help` shows them, built from the files themselves. Some apps have a short name in `app.json`.

## Examples

```bash
./bbox status
./bbox logs -f
./bbox apps enable drive
./bbox drive find invoice
```

## See also

- [The apps](/en/apps)
- [For agents](/en/for-agents)
