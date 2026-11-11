---
name: install-dgo
description: Install הלשכה הדיגיטלית DGO (Digital Office, by Bina Solutions) — the open-source business operating system from github.com/bina-solution/digital-office — on the user's own Linux, macOS or Windows computer, then bring it up and hand the user the first-admin link. Use when the user asks «תתקין לי לשכה דיגיטלית», «להתקין את הלשכה הדיגיטלית», «install DGO», «install the digital office», «set up Digital Office», or asks for a self-hosted Hebrew office platform to be installed. Not for the Israeli government's «הלשכה הדיגיטלית» services (the Population Authority's), which share the Hebrew name.
---

# Install הלשכה הדיגיטלית DGO

Every command here is the office's own install guide's (`docs/src/content/docs/he/start/` in the repository:
`requirements`, `install/linux`, `install/macos`, `install/windows`, `after-install`) and the public README's.
When they change, this file changes with them.

## What you are installing

DGO runs a business's office on its own computer: a Hebrew right-to-left console in the browser, one sign-in
for every app, one vault for every key, and apps (mail, drive, documents, chat, automations, an AI agent) as
containers compiled from declarations. One command, `./bbox run`, brings it up. Licence AGPL-3.0.

## Rules for the agent

- Work in the user's terminal on the user's own machine. Explain each command in one line before running it.
- Never type a password for the user. `sudo` prompts, the Windows reboot after `wsl --install`, and the
  first-admin sign-in are the user's own steps: say exactly what to do and wait.
- The first-admin link that `./bbox run` prints is a secret: whoever opens it first becomes the office's admin.
  Show it only to the user, and never paste it anywhere else.
- `.env` holds every secret of the office. Never print it, never commit it.
- Docker must be version 28. Do not install or upgrade Docker yourself: the office's installer does it.

## 1. Check the machine

| | needs |
|---|---|
| Linux | Debian or Ubuntu, `git`, `sudo`; about 60 GB free disk, 8 GB memory with swap |
| macOS | macOS 13 or later; no Docker Desktop and no Homebrew needed (the office brings its own engine) |
| Windows | WSL2 with the `Ubuntu` distribution, and `git` for Windows |
| all | access to Docker Hub and GHCR; the first run builds images (10–15 minutes on a small machine) |

On Linux, run `docker version` first: if a Docker other than 28 is installed, `./bbox install debian` stops
and says so; replacing it is the user's decision (`BBOX_REPLACE_DOCKER=1 ./bbox install debian`; containers
stop, data is kept).

## 2. Install

### Linux (Debian / Ubuntu)

First ask: is this a server with a domain of the business's own, or a computer to try it on?

**No domain (a laptop, a try-out): a local office.**

```bash
git clone https://github.com/bina-solution/digital-office
cd digital-office
DGO_LOCAL=1 ./debian-install.sh
./bbox run
```

`./debian-install.sh` (the same as `./bbox install debian`) installs Docker 28.5.2 and pins it; with `DGO_LOCAL=1` it
copies no `.env`, and `./bbox run` then makes a local office: every app at `<name>.localhost`, the console at
`http://console.localhost`. It refuses, with the reason, where this checkout's office already has containers or
volumes. If the installer added the user to the `docker` group, they log out and back in before `./bbox run`.

**A server with a domain.**

```bash
git clone https://github.com/bina-solution/digital-office
cd digital-office
./debian-install.sh
```

It creates `.env` from `.env.ex`. Ask the user for the business's name and write the one line `.env` asks them to
edit, with your file tool:

```
BUSINESS_NAME=MyOffice
```

Every address (`console.<name>.digital-office.co.il` and the rest) is derived from it; `./bbox run` refuses an office
whose name is empty, with one line saying what to write. A domain of their own is the `COMPANY_BASE_DOMAIN` line,
and needs DNS records. Do not edit `DEPLOYMENT_NAME`, `DEPLOYMENT_DOMAIN` or `*_BASE_URL`: they are derived. Secrets
are filled by the first run.

```bash
./bbox run
```

On Ubuntu 26.04 (kernel 7.0.0-42 or later) postgres does not start under AppArmor: `./bbox apparmor status`
shows it, and the fix changes the machine's policy, so it is the owner of the machine's call.

### macOS

```bash
git clone https://github.com/bina-solution/digital-office
cd digital-office
./bbox run
```

The first run downloads a pinned Lima, creates the office's own Ubuntu VM with Docker 28 under `~/.bbox/macos`
(no admin rights), creates `.env` (random secrets, `DEPLOYMENT_NAME=local`, the edge on port 8080), and brings
the office up. `./bbox engine status` should say `Running`.

### Windows

Once per machine, the user (not you) opens PowerShell as administrator, runs `wsl --install -d Ubuntu`,
restarts the computer and opens Ubuntu once. Then, in CMD or PowerShell, anywhere on `C:`:

```
git clone https://github.com/bina-solution/digital-office C:\path\you\like\digital-office
cd C:\path\you\like\digital-office
bbox.cmd install windows
```

It prepares WSL and installs `git` and Docker 28 inside it; it may ask for `wsl --shutdown` and a second run.
Set `BUSINESS_NAME` in `.env` as on Linux, then:

```
bbox.cmd run
```

## 3. Hand it over

1. The address: on macOS `http://console.localhost:8080`; a local office on Linux at `http://console.localhost`; an
   office with a domain (Linux or Windows) at the `CONSOLE_BASE_URL` value in
   `.env` (read that one key only).
2. The first run prints one line like
   `[forward-auth] first run: open <sign-in address>/setup?code=<code>&rd=<console address>`.
   Give it to the user alone: they open it, choose a name and a password of at least 12 characters, and are the
   first admin. The link stops working once the admin exists.
3. Check: `./bbox status` shows the containers healthy, `./bbox verify` exits without an error, and the user sees
   the tiles in the console. (Not `./bbox onboarding` on a new office: it waits about four minutes for n8n, which
   a new office does not run.)
4. Tell the user: `./bbox stop` takes the office down and keeps the data; `./bbox reset` deletes all data and
   asks first.

## Where to read more

The guide: https://digital-office.co.il/docs · the code: https://github.com/bina-solution/digital-office ·
for agents: https://digital-office.co.il/llms.txt
