---
title: Backup
description: Keep the whole office in one archive with bbox export, and keep the archive somewhere safe.
---

## Why

Most of what the office knows is not in its folder. The databases, the automations, the documents, the users and the sync state are in Docker volumes, outside the folder. A `zip` of the folder brings back an office that starts and knows nothing.

`bbox export` keeps all of that in one archive.

## Before you start

- The office is running.
- There is room on the disk for the archive.

## The steps

1. **Back up:**

   ```bash
   ./bbox export
   ```

   The archive is written to `exports/` inside the office's folder, in a folder named after the office, the kind of backup and the time.

2. **Choose how much to keep.** The default is `full`: everything, including the run history and the document-reading cache. Without them:

   ```bash
   ./bbox export --mode config
   ```

3. **Keep the archive somewhere else.** The archive also holds `.env` and the keys. Keep it the way you keep a password.

   `bbox export` refuses to write to a folder `git` does not ignore, so that the secrets do not get into the repository.

## One app only

```bash
./bbox export --app <app>
```

An archive of only this app's data.

## Before moving to another computer

```bash
./bbox export --quiesce
```

`--quiesce` stops whatever writes to the data during the backup, and starts it again at the end. That way every database is kept from the same moment. It is right for a move, not for backing up an office people are working in.

## If the backup was cut off

Run the same command again. What was already saved is not written again.

## How to check it worked

The archive's folder has a `manifest.json` file. It lists every file that was saved.

```bash
ls exports/
```

The real test of a backup is a restore. See [Restore](/en/backup/restore).

## See also

- [Restore](/en/backup/restore)
- [Data management](/en/apps/data-management): the nightly backup, and what it does not do yet
- [What not to do](/en/admin/never-do)
