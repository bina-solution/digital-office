---
title: Uninstall
description: Take the office off the computer — stop it and keep the data, or delete everything — on Linux, macOS and Windows, and know what each step deletes.
---

## Why

The office's data (databases, files, app settings) is not in the repository's folder. It is in Docker volumes.
So deleting the folder does not delete the data, and deleting the volumes does not delete the folder. Every step here says what it deletes.

## Before you start

- Want to keep something? [Back up](/en/backup) first.
- Every command runs from the office's folder. On Windows every `./bbox` is `bbox.cmd`.

## The steps

1. **Stop, and keep the data.** The containers come down and the data stays. `./bbox run` brings the office up again, as it was.

   ```bash
   ./bbox stop
   ```

2. **Delete all the office's data.** The command asks before it deletes. It deletes every volume of this office: the databases, Redis, n8n and the other apps. There is no way back without a backup.

   ```bash
   ./bbox reset
   ```

3. **Remove what was installed, by computer:**

   - **macOS:** the office's engine is a virtual machine of its own. This command deletes its disk, and with it every image, container and volume of the office on the Mac. It requires `--force`:

     ```bash
     ./bbox engine destroy --force
     ```

     Everything the engine downloaded and set up is in the folder `~/.bbox/macos`. Deleting the folder removes the engine entirely.
   - **Windows:** the office and its Docker run inside WSL's `Ubuntu` distribution, and the volumes are inside it too. `wsl --unregister Ubuntu` deletes the distribution's disk, and with it every volume. The command also deletes anything else you have in that distribution. Want to keep a copy? Run `wsl --export Ubuntu <file>` first. After the deletion a `.wslconfig` file and Windows' WSL components remain. They are not deleted.
   - **Linux:** Docker stays installed. The office installed it (version 28, pinned), but it is a tool of the computer, and removing it is an ordinary Docker removal.

4. **Delete the repository's folder.** The folder also holds `.env`, with all the office's secrets. If you may still want to bring the office back from the backup, keep `.env` somewhere safe first.

## How to check it worked

- After `./bbox stop`: `./bbox status` shows no running containers.
- On macOS, after `./bbox engine destroy --force`: `./bbox engine status` prints `not created`. Check before you delete `~/.bbox/macos`, because without the folder the command downloads the engine's parts again.

## Going further

- [Backup](/en/backup)
- [Restore](/en/backup/restore)
- [What not to do](/en/admin/never-do)
