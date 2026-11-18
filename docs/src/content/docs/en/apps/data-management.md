---
title: Data management
description: "The data app: what the office holds, the nightly backup into a repository, and what the backup does not do yet."
---

## What it is

«Data management» (`data-management`) sums up the office's data, backs it up and restores it. It is part of the base of every office (layer 2). In the centre it is the «Data management» tile in the «Infrastructure» group, for administrators only.
How to back up and restore by hand: [Backup](/en/backup) and [Restore](/en/backup/restore).

## From the command line

| Command | What it does |
|---|---|
| `./bbox data view` | Everything the office holds, app after app. `--gaps-only` shows only what has no backup |
| `./bbox data export` | An archive of everything a copy of the folder would not catch. `--app` limits it to one app |
| `./bbox data import <DIR>` | Brings an archive back to this computer. It does not write to the office the archive came from without `--force` |

Both commands ask the app's service for the work and show its log. The commands `./bbox export` and `./bbox import` on the [Backup](/en/backup) page run the same program directly, on the whole office.

## The nightly backup

A backup of the office runs into a restic repository on a target: on this computer, or in a repository a linked office holds. A target that has a set time is backed up every night, and a night the service was off is backed up when it comes back.

**A new office has no target, so there is no nightly backup.** A target is defined only in the service's `backup-targets.json` file. There is no screen or command yet that adds a target. Until there is a target, back up by hand: [Backup](/en/backup).

- **One key.** The repository's key is kept in the office's vault, and created once, only when the repository does not exist yet. If the key is missing against an existing repository, the backup stops: a new key would not open the existing repository.
- **Keeping and pruning.** A target keeps every backup and deletes nothing, unless it was explicitly defined that deleting is allowed on it. On such a target 7 daily, 4 weekly and 6 monthly backups are kept, and the rest is deleted. A target at another office never deletes.
- **Checking.** Every run reads a seventh of the repository, so every byte is read once a week.
- **A backup that did not start says why.** It does not report success silently.

**What the backup does not do yet:**

- In a new office it does not run at all, because there is no target.
- Every backup is one snapshot of the whole office, not one per app.
- Its parts are compressed, so the repository keeps every night in full, not only what changed.

## How to check it works

- The «Data management» tile opens and shows the summary.
- `./bbox data view --gaps-only` shows what is not backed up yet.

## Going further

- [Backup](/en/backup)
- [Restore](/en/backup/restore)
- [Office](/en/concepts/office)
