---
title: For agents
description: The rules for a coding agent that installs or runs an office — what to do, and what never to do.
---

## Who this page is for

For a coding agent (or a person) working inside a folder of the digital office. The rules here are what the office needs so it does not break silently.

## To start

- No office on the computer yet? The install is one command: `curl -fsSL https://digital-office.co.il/install.sh | bash`. What it does, and what is left for the person: [Install with an agent](/en/start/agent-prompt).
- The repository's entry file is `AGENTS.md`. Read it first.
- `./bbox help` shows every command of the office, and every verb of every app.
- `./bbox context` says what this office runs now, and `./bbox context <app>` what one app is and does. Ask the office, not a document.
- On Windows, every command is `bbox.cmd` instead of `./bbox`.

## What to do

1. **Run the office only through `bbox` or `./scripts/dc`.** The services are built from the declarations into `.generated/`.

2. **Change a declaration, not an output.** What runs is set in `apps/*/app.json` and in `platform.state.yaml`. `.generated/` is not edited by hand.

3. **Turn apps on and off with the office's command:**

   ```bash
   ./bbox apps enable <app>
   ./bbox apps disable <app>
   ```

   The command only writes the decision. For it to run:

   ```bash
   ./bbox run
   ```

4. **Check against real output before saying «done».**

   ```bash
   ./bbox status
   ./bbox verify
   ```

5. **Back up before any deletion.**

   ```bash
   ./bbox export
   ```

6. **Explain a dangerous command before running it.** Any command that deletes, moves, stops or writes files, services or data: one line that says what it does and what could break.

## What never to do

- **No direct `docker compose`.** `compose.yml` holds only the shared network. A direct command finds zero services and exits successfully, having done nothing.
- **No `docker compose -f apps/<app>/docker-compose.yml`.** It opens a second project with the same container names, and the next `bbox run` fails.
- **No `docker cp` as a deployment.** The change lives only until the container is rebuilt, and `bbox run` rebuilds.
- **Docker: ask the engine, not its version.** The installers pin Docker 28.5.2. On Docker 29 you need `DOCKER_MIN_API_VERSION=1.24`. Without it the router does not route, with no error message.
- **Do not print secrets.** `.env` holds all the office's secrets and does not go into `git`.
- **No `./bbox reset` unless the office's owner asked for it.** The command deletes all the data.

## How to check the office is healthy

```bash
./bbox status
./bbox verify
```

`bbox verify` exits with a non-zero code when something is broken.

## See also

- [The command line](/en/reference/cli)
- [What not to do](/en/admin/never-do)
- [Is the office healthy?](/en/admin/health)
