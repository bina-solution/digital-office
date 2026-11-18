---
title: Install with an agent
description: Let a coding agent (Claude or any other agent) install the office on your computer — with one command or with the plugin — and what is left for you alone to do.
---

## Why

The install steps are written so that an agent can run them too: one command that runs the guide's steps, and a Claude plugin that knows how to carry them out.
A few steps stay yours in any case: the computer's password, one restart on Windows, and the first sign-in to the office.

## Before you start

- A computer that meets the [requirements](/en/start/requirements).
- An agent that runs commands in a terminal on this computer. An agent running on another computer cannot install on yours.
- `git` installed. On Linux: `sudo apt-get install -y git`. On a Mac: `xcode-select --install`.

## The short way: one command

You can run it yourself, or ask the agent to run it:

```bash
curl -fsSL https://digital-office.co.il/install.sh | bash
```

What it does, by computer:

- **Linux (Debian or Ubuntu), without a domain:** downloads the repository into the folder `~/digital-office`, runs `DGO_LOCAL=1 ./debian-install.sh` and then `./bbox run`. The result is a local office.
- **Linux, on a server with a domain:** give it the name of the business, and it writes it to the `BUSINESS_NAME` line in the `.env` file:

  ```bash
  curl -fsSL https://digital-office.co.il/install.sh | DGO_BUSINESS_NAME=MyOffice bash
  ```

  The business name: English letters, digits and hyphens only.
- **macOS:** downloads the repository and runs `./bbox run`, which sets up the office's engine.
- **Windows:** the command does not install. It prints the three commands you run in CMD or PowerShell, as in [Install on Windows](/en/start/install/windows).

Two things can be changed: `DGO_DIR` is the folder (by default `~/digital-office`), and `DGO_REF` is the branch or version to download.

## With Claude: the plugin

The office is also a Claude plugin. In Claude Code:

```
/plugin marketplace add bina-solution/digital-office
/plugin install digital-office@digital-office
```

Then write to it «install a digital office for me». It asks whether this is a server with a domain or a computer to try it on, and runs the matching path.
In claude.ai or in the Claude apps, upload the repository's folder `packaging/claude/skills/install-dgo/` as a Skill.

## Another agent

Give it the address [digital-office.co.il/llms.txt](https://digital-office.co.il/llms.txt). That is the file agents read, and the command is written at its top. For example:

> Install the digital office DGO on this computer according to https://digital-office.co.il/llms.txt. Do not type any password for me, and at the end give the link that contains /setup?code= to me alone.

## What is left for you alone

- **The computer's password.** When `sudo` asks for a password, you type it, not the agent.
- **On Windows, once:** open PowerShell as administrator, run `wsl --install -d Ubuntu`, restart the computer and open Ubuntu once.
- **The first sign-in.** At the end of the run a line is printed with a link that contains `/setup?code=`. Whoever opens it first becomes the office's administrator. Open it yourself, and do not pass it to anyone, not even the agent. Then continue with [After the install](/en/start/after-install).
- **The `.env` file.** It holds all the office's secrets. An agent has no need to print it.

## How to check it worked

- The command ends with the address of the centre, as the office recorded it in `CONSOLE_BASE_URL` in the `.env` file.
- `./bbox status` shows the containers healthy, and `./bbox verify` exits without an error.

## Going further

- [Requirements](/en/start/requirements)
- [Install on Linux](/en/start/install/linux)
- [After the install](/en/start/after-install)
- [For agents](/en/for-agents)
