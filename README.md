# DGO — the digital office · הלשכה הדיגיטלית

**DGO – הלשכה הדיגיטלית: a whole business office on a computer of your own — mail, documents and their
automations, meetings, projects, files, chat and an AI agent. Open source, self-hosted, Hebrew-first. By BINA
Solutions — [digital-office.co.il](https://digital-office.co.il).**

[עברית](README.he.md) · [Contributing](CONTRIBUTING.md) · [Security](.github/SECURITY.md) · AGPL-3.0

<div dir="rtl">

**בעברית:** הלשכה הדיגיטלית מבית בינה סולושנס (BINA Solutions) היא לשכה עסקית שלמה על מחשב משלכם — דואר,
מסמכים ואוטומציות, פגישות, פרויקטים, קבצים, צ׳אט וסוכן AI. קוד פתוח, מותקן אצלכם, בעברית מהיסוד. התקנה בפקודה אחת,
וכל השאר ב-[README.he.md](README.he.md):

```bash
curl -fsSL https://digital-office.co.il/install.sh | bash
```

</div>

DGO runs a small business's office on one machine of its own — a server, a laptop, or a Mac. Every app is a
container, the whole set is compiled from declarations, and one command brings it up. The office's data stays on
that machine; the AI agent talks to the model provider whose key you give it. The screens are Hebrew-first and
right-to-left, and English is built in (`./bbox lang en`).

**Status:** 0.3 — early, and used every day by the businesses that build it and their first clients. Expect it to
move fast. (Not related to the Israeli government service of the same Hebrew name.)

## What you get

| | |
|---|---|
| **One home screen** | the console: every app of the office behind one sign-in, on desktop and phone |
| **Mail** | the office's own mail, with labels and rules |
| **Incoming documents** | invoices and receipts read by OCR, sorted and filed by automations |
| **Automations** | n8n workflows, kept in the repository as code |
| **Meetings** | video meetings (Jitsi) with recordings and transcripts |
| **Projects** | a project board (Plane) with tasks and modules |
| **Files** | a shared drive, with Google Drive alongside |
| **Chat** | the office's chat, with WhatsApp and Telegram through its connections |
| **An AI agent** | an agent that works inside the office, with the office's tools — and a browser it can drive |
| **Linked offices** | offices link to each other over an encrypted link and lend each other apps, without opening them to the internet |

**[The app catalogue](apps/README.md)** lists every app of this release, from its own manifest; each app's folder
says what it is (`app.json`) and how it is operated (`AGENT.md`).

## Install

**One command** (Debian/Ubuntu and macOS; on Windows it explains the WSL preparation):

```bash
curl -fsSL https://digital-office.co.il/install.sh | bash
```

**From a clone**, on a Debian or Ubuntu server:

```bash
git clone https://github.com/bina-solution/digital-office
cd digital-office
./debian-install.sh       # Docker and its compose plugin, and a .env from .env.ex (an existing .env is kept)
./bbox run                # compile the office, then bring it up
```

Before `bbox run`, set your domain, your business name and the other values in `.env`. If the install script added
you to the `docker` group, log out and back in first.

**No domain — a laptop, or a first look:** skip the `.env`, and the office makes a local one by itself:

```bash
DGO_LOCAL=1 ./debian-install.sh   # Docker and its compose plugin, and no .env
./bbox run                        # no .env: a local office, every app at <name>.localhost
```

A machine that already ran an office and lost its `.env` is refused, not given a new one: new secrets would not open
the data that is there.

- **macOS:** clone, then `./bbox run` — it sets up its own engine and writes a local `.env`; the office is at
  `http://console.localhost:8080` ([packaging/macos.md](packaging/macos.md)).
- **Windows:** once per machine, from PowerShell as administrator: `wsl --install -d Ubuntu`, restart, open Ubuntu
  once. Then clone into a folder on `C:`, and from it run `bbox.cmd install windows` (it may ask for one
  `wsl --shutdown` and a second run), then `bbox.cmd run` ([ai/context/running-on-wsl.md](ai/context/running-on-wsl.md)).
- **With Claude Code:** `/plugin marketplace add bina-solution/digital-office`, then
  `/plugin install digital-office@digital-office`, and the agent installs the office for you.

**What a host needs:** an office of about 60 containers, with public sites and meeting recordings, runs on 2 CPUs and
8 GB of RAM with swap, and takes about 44 GB of disk for its images and data. An 8 GB Apple Silicon Mac runs a local
office. Fewer apps need less ([ai/context/running-the-stack.md](ai/context/running-the-stack.md)).

## The first hour

1. **Become the admin.** The first `./bbox run` prints one line,
   `[forward-auth] first run: open <sign-in address>/setup?code=…`. Open it before anyone else: you choose a name and a
   password of at least 12 characters and are the office's first admin. The link stops working once you are.
2. **Open the console** — `http://console.localhost` (`:8080` on a Mac), or your domain's console address
   (`CONSOLE_BASE_URL` in `.env`).
3. **Give the agent a model.** In «Connections», add a key of the model provider you choose; the agent uses it.
4. **Turn on what you need:** `./bbox apps enable <app>`, or the app manager's screen.

Day to day: `./bbox status` shows what runs; `./bbox stop` takes the office down and keeps the data; `git pull` then
`./bbox run` brings in a new version; `./bbox export` / `./bbox import` carry the whole office to another machine.

## How it works

- **Declarations, not scripts.** Each app is a folder: its manifest (`apps/<app>/app.json`) and, when it runs a
  service, its compose file. The compiler (`platform/manager/reconcile.py`) reads them with the office's own choices
  (`platform.state.yaml`) and renders the running set into `.generated/`; `bbox` brings Docker in line with it.
- **A core every office gets** (`platform-base/`): the console, sign-in (authentik), the edge (Traefik), Postgres and
  Redis, the app manager, the credential vault, notifications and security.
- **Apps an office chooses** (`apps/`): each with its own screen, API and CLI (`./bbox <app> …`), to one standard
  ([ai/context/app-cli-api-standard.md](ai/context/app-cli-api-standard.md)).
- **One look.** Every screen is built from one design system — one palette, right-to-left first.
- **Ask the office, not a document.** `./bbox context [app]` says what the office and each app are and do now;
  `./bbox computers map` draws the whole network of linked offices, live.

Do not run `docker compose` directly: the services are compiled into `.generated/`, so a bare `docker compose up`
starts nothing. Use `./bbox`, or `./scripts/dc` for compose itself. `./bbox help` lists every command.

## Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) — the short entry file for people and
for AI coding agents. [ai/context/build-your-first-app.md](ai/context/build-your-first-app.md) shows how an app is
written, and `scripts/refactor/` holds the gates every change passes. Report a security problem privately:
[.github/SECURITY.md](.github/SECURITY.md).


## License

DGO — the digital office
Copyright (C) 2023 Bina Solutions

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

Third-party components keep their own licenses: see [NOTICE.md](NOTICE.md) and [LICENSES/](LICENSES/).
