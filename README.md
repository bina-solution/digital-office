# DGO — the digital office

DGO runs a small business's office on one machine of its own: mail, documents and their automations,
video meetings with transcripts, a project board, a shared drive, chat, and an AI agent that works
inside the office. Every app is a container, the whole set is compiled from declarations, and one
command brings it up. The screens are Hebrew-first and right-to-left. DGO is made by BINA Solutions.

## How it is built

- **Declarations, not scripts.** Each app is a folder with its manifest (`apps/<app>/app.json`) and,
  when it runs a service, its compose file. The compiler (`platform/manager/reconcile.py`) reads them, together with the
  office's own choices in `platform.state.yaml`, and renders the running set into `.generated/`.
  `bbox` then brings Docker in line with it.
- **The core** (`platform-base/`) is what every office gets: the console (the office's front screen),
  sign-in (authentik), the edge (Traefik), Postgres and Redis, the app manager, the credential vault
  (connections), notifications and security.
- **The apps** (`apps/`) are chosen per office: automations (n8n), document OCR and extraction
  (apitools), incoming documents (indox), mail, drive, chat, video meetings (meet, on Jitsi), a project
  board (project-pln, on Plane), a browser for agents (browser42), the office's agent (bina-ds), sites,
  and more. `ls apps/` is the full list.
- **Offices link to each other** (dgo-extend): one office can serve an app to another over an encrypted
  link, without opening it to the internet.

## Install

On a Debian or Ubuntu server:

```bash
git clone https://github.com/bina-solution/digital-office
cd digital-office
./debian-install.sh       # Docker and its compose plugin, and a .env from .env.ex (an existing .env is kept)
./bbox run                # compile the office, then bring it up
```

Before `bbox run`, set your domain, your business name and the other values in `.env`. If the install
script added you to the `docker` group, log out and back in first.

On a Mac, `./bbox run` sets up its own engine and writes a local `.env` (see `packaging/macos.md`).
On Windows, use `bbox.cmd run`, which runs through WSL (see `ai/context/running-on-wsl.md`).
`./bbox help` lists every command.

Do not run `docker compose` directly. The services are compiled into `.generated/`, so a bare
`docker compose up` starts nothing. Use `./bbox`, or `./scripts/dc` for compose itself.

## Working on it

`ai/context/README.md` is the index of the design notes, and `ai/context/build-your-first-app.md` shows
how an app is written. `scripts/refactor/` holds the gates every change must pass.


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
