---
title: Restore
description: Bring an office back from a bbox export archive, into a new folder or one app.
---

## Why

A `bbox export` archive brings the office back: the databases, the automations, the documents, the users and `.env`.

## Before you start

- An archive from `./bbox export`. See [Backup](/en/backup).
- An office installed in a new folder. See [Start — choose a computer](/en/start).

## The steps

1. **Put the archive in the new folder,** inside `exports/`.

2. **Restore:**

   ```bash
   ./bbox import
   ```

   Without a folder, the command takes the latest archive in `exports/`. Another archive:

   ```bash
   ./bbox import exports/<archive>
   ```

3. **Read what the command says.** It writes which office the archive came from, and which it is restored into. Before it writes, it checks every file in the archive by `sha256`. After the restore, it compares the number of rows in every table to the source.

## One app only

```bash
./bbox import --app <app>
```

Brings back only this app's data, even from an archive of the whole office. The rest is not touched.

## What the command refuses to do

- **Write over the office the archive came from.** This is a protection. If that really is what you want, `--force`.
- **Restore an archive in another format version.**

## How to check it worked

```bash
./bbox status
./bbox verify
```

And sign in to the centre: the apps, the files and the users that were in the original office.

## See also

- [Backup](/en/backup)
- [Is the office healthy?](/en/admin/health)
