---
title: Office
description: What one office is made of on the computer — a folder, a .env file, Docker volumes and one name every address derives from — and what tells one office from another.
---

## The problem

«Office» sounds like a room, but on the computer it is something defined. Without knowing what it is made of, it is hard to know what to back up, what to delete, and why an office refuses to start.

## The idea

### Four parts on one computer

| The part | What it is | Note |
|---|---|---|
| The repository's folder | The code and the declarations: `app.json` for each app, and `platform.state.yaml`, which says which apps are on | Comes from `git clone` |
| `.env` | The office's settings and secrets | Does not go into `git`. It holds keys that apps encrypt with. For example, n8n's credentials open after a restore only with the key in `.env` |
| Docker volumes | The data: databases, files, app settings | Not in the folder. `./bbox reset` deletes them |
| `.generated/` | What the compiler built from the declarations | Not edited by hand. Rebuilt on every run |

On macOS there is a fifth part: the engine, a virtual machine the office sets up in the folder `~/.bbox/macos`.

### One name, and everything else derives from it

In an office with a domain, the only line you edit in `.env` is `BUSINESS_NAME`, the name of the business. From it derive:

- `COMPANY_SLUG`: the name in lower case with hyphens, for example `my-office`.
- `DEPLOYMENT_NAME`: the suffix of the office's container names.
- `DEPLOYMENT_DOMAIN`: the office's domain, which all its addresses depend on, for example `console.my-office.digital-office.co.il`.

One DNS record, `*.<slug>.<domain>`, covers every address of such an office, the certificates included.
If the name is empty, `./bbox run` refuses and says in one line what to write.

### An office without a domain

No `.env`? `./bbox run` creates a local office by itself. Its name is `local`, every app is at the address `<app>.localhost`, and the centre at `http://console.localhost` (on a Mac: with `:8080`).

### An office is not built on top of data

If there is no `.env`, but this folder already has containers or volumes, `./bbox run` refuses. To it the `.env` is missing, not new. Bring it back from a backup, and the run continues.

## What this makes possible

- You know what to back up: the volumes (through [Backup](/en/backup)) and `.env`.
- You know what each step deletes: [Uninstall](/en/start/uninstall) separates stopping, deleting the data and deleting the folder.
- The same folder and the same `.env` on another computer bring up the same office. Offices on different computers connect to each other with a [link](/en/concepts).

## Going further

- [The concepts](/en/concepts)
- [After the install](/en/start/after-install)
- [The architecture](/en/architecture)
