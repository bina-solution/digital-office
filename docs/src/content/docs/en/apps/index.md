---
title: The apps
description: Every app of the office, by layer, with its id and what is on in a new install.
---

## How to read the table

- **Id** is the app's name in commands: `./bbox apps enable <id>`.
- **Layer**: 1 and 2 are the base of every office (`platform-base/`). 3 are apps you add (`apps/`).
- **On in a new install**: what the default file `platform.state.default.yaml` says. An app not listed in it is off, except «Containers», which is on as long as the office's state (`platform.state.yaml`) does not say otherwise.
- **Administrators only**: a person you invited to the office does not open this app.

![The «Apps» screen with the list of apps and the switches](TODO-shot: app-management, the installed apps tab, demo office, desktop 1440x900, light theme)

## The base

| Name | Id | Layer | On in a new install | Administrators only |
|---|---|---|---|---|
| App Management | `app-management` | 1 | yes | yes |
| Edge router | `traefik` | 1 | yes | yes |
| Database | `postgres` | 1 | yes | |
| Cache and queues | `redis` | 1 | yes | |
| Identity and sign-in | `forward-auth` | 1 | yes | |
| Users and sign-in | `authentik` | 1 | no | |
| Connections | `connections` | 1 | yes | yes |
| Self-healing | `autoheal` | 1 | yes | |
| Following the stable version | `follow-runner` | 1 | no | |
| Containers | `containers` | 1 | yes | yes |
| Console (the centre) | `console` | 2 | yes | |
| Notifications | `notifications` | 2 | yes | |
| Machine | `machine` | 2 | yes | yes |
| Data management | `data-management` | 2 | yes | yes |
| UI library | `bina-ui` | 2 | yes | |
| Error tracking | `glitchtip` | 2 | no | yes |
| Security | `security` | 2 | no | yes |
| HTTPS redirect | `https-redirect` | 2 | no | |

## Apps

| Name | Id | On in a new install | Administrators only |
|---|---|---|---|
| Bina | `bina-ds` | yes | yes |
| Files | `drive` | yes | |
| Mail | `mail` | yes | |
| INDOX | `indox` | yes | |
| API Tools | `apitools` | yes | |
| Automations | `n8n` | no | yes |
| Office storage | `drive-local` | no | |
| Google Drive | `drive-google` | no | |
| Documents | `documents` | no | |
| My Docs | `my-docs` | no | |
| Signatures | `esign` | no | |
| Projects | `project-pln` | no | |
| Video meetings | `meet` | no | |
| Chat | `chat` | no | |
| Telegram | `telegram` | no | yes |
| Telegram TV | `telegram-tv` | no | yes |
| Slack | `slack` | no | yes |
| Element | `element` | no | yes |
| Signal | `signal` | no | yes |
| Social networks | `social-list` | no | yes |
| Identity | `digital-assets` | yes | yes |
| Entities | `entities` | yes | yes |
| Sites | `sites` | no | yes |
| Domains | `domains` | no | yes |
| InterNIC | `domain-internic` | no | yes |
| NewsFlow | `newsflow` | no | |
| Computers | `computers` | no | yes |
| Control centre | `dashboard` | no | yes |
| Office extension | `dgo-extend` | no | yes |
| Console on the LAN | `lan-console` | no | |
| Network | `office-routes` | no | |
| Browser42 | `browser42` | no | yes |
| Claude Desktop | `bina-claude` | no | yes |
| Raphael | `raphael` | no | |
| OpenHands | `openhands` | no | yes |
| Ollama | `ollama` | no | |
| Google Workspace Agent | `google-workspace-agent` | no | |
| Operative Collective | `operatives` | no | |
| Version control | `git` | no | yes |
| Terminal | `terminal` | no | |
| Any Concurrency | `any-concurrency` | no | yes |
| Archify | `archify` | no | |
| FreeCAD | `cad` | no | |
| Parametric models | `cad-api` | no | |
| Calculator | `calculator` | no | |
| Obsidian | `obsidian` | no | yes |
| Portainer | `portainer` | no | yes |
| RedisInsight | `redisinsight` | no | yes |
| Supabase | `supabase` | no | yes |
| Hello Bina | `hello-bina` | no | |

## See your own office's list

```bash
./bbox apps list
```

The «Apps» screen shows the same list, with each app's state.

## See also

- [Turn an app on and off](/en/use/add-app)
- [The command line](/en/reference/cli)
