---
title: Files
description: "The office's one place for files: drives, connecting Google Drive and what it needs today, working by path, and the commands from the terminal."
---

## What it is

«Files» (`drive`) is the office's one place for files: documents, pictures, recordings and videos. In the centre it is the «Files» tile in the «Business» group, and on a phone it has a place in the bottom bar.
How to use it day to day: [Files](/en/use/files).

## Drives

Every drive is a [connection](/en/concepts/connection). A drive can be a profile of the office's own storage, for example `admin`, or a Google Drive account.

## Connect Google Drive

On the «Files» screen, under «Drives», «Connect Google Drive» offers two ways:

| Way | What it gives | What it needs today |
|---|---|---|
| «Sign in with Google» | The account's whole Drive, and its Gmail too, with one approval | **The office's Google client**, in `.env` (`N8N_GOOGLE_OAUTH_CLIENT_ID` and `N8N_GOOGLE_OAUTH_CLIENT_SECRET`; a change saved only in «Connections» is not used to renew the connection), whose registered return address is `<OAUTH_RELAY_URL>/oauth/relay`. The default of `OAUTH_RELAY_URL` is the public door of the offices of DGO's makers, and it accepts only their client. An office with a public address of its own declares itself there. **On offices on the shared client this does not work today:** Google answers `invalid_client`, because the client was deleted at Google. The screen says so and offers the second way |
| «Share a folder with the office» | Only the folders shared with the office. It reads, downloads, moves, renames and moves to the bin. It does not create new files | **Works today.** It needs, once, an address for the office at Google: a service account. Whoever manages the office adds it with its JSON file, with the «Add the office's address» button |

How to share a folder, once the office has an address:

1. Copy the office's Google address from the screen.
2. In Google Drive: right-click the folder › «Share» › paste the address › «Editor» › «Send».
3. Go back to the screen and click «Check — what was shared?». It takes up to a minute.

**The screen comes with the version.** «Connect Google Drive» and the Google engine went into the code on 9 November 2026. An office still running an earlier version does not see this screen, until it gets the new version. See [Updating the office](/en/admin/updates).

## Working by path

Every file and folder is called by its path, like `/Documents/Contracts`, and not by a number.
Apps write here by themselves. For example, meeting recordings and transcripts are kept under `/Meetings`. A folder an app writes to is marked as a system folder: it cannot be renamed, moved or deleted.

## From the command line

| Command | What it does |
|---|---|
| `./bbox drive find <text>` | Files and folders whose name contains the text, with the paths |
| `./bbox drive ls <path>` | What is in a folder |
| `./bbox drive get <path> <local>` | Downloads a file to this computer |
| `./bbox drive put <local> <folder>/` | Uploads a file to a folder, and creates it if needed |
| `./bbox drive mkdir <path>` | Creates a folder, or returns the existing one |
| `./bbox drive rm <path>` | Moves to the bin. `restore` brings it back |
| `./bbox drive profile list` | Every drive, and which is the default |
| `./bbox drive flow` | The events: uploads, folders, bin |
| `./bbox drive help` | Every command |

The flag `-p <drive>` chooses a drive. Without it the command works on the default.

## How to check it works

- The «Files» tile opens and shows the folders.
- `./bbox drive ls /` shows what is in the top folder.

## Going further

- [Files: how to use it](/en/use/files)
- [Connection](/en/concepts/connection)
- [App Management](/en/apps/app-management)
