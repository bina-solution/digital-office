---
title: Is the office healthy?
description: Three commands that say whether the office is healthy, and where to look when it is not.
---

## Why

Before a change, after a change, and when something looks wrong: check what runs, what is ready, and what the logs say.

## Before you start

- A terminal in the office's folder.

## The steps

1. **What runs:**

   ```bash
   ./bbox status
   ```

   A snapshot: the containers, the automations and the permissions. A container counts as down only if its app is on.

2. **Is the office ready:**

   ```bash
   ./bbox verify
   ```

   Checks the computer, the office and the permissions. Exits with a non-zero code when something is broken.

3. **What the logs say:**

   ```bash
   ./bbox logs
   ./bbox logs <svc> -f
   ```

   Without a name: the logs of every service, the last 200 lines. `-f` keeps following.

4. **How much room and memory are left:**

   ```bash
   ./bbox machine overview
   ./bbox machine storage
   ```

   The first: processor, memory, disk, and what each container uses. The second: what takes up the disk.

5. **The permissions for outside services:**

   ```bash
   ./bbox onboarding --auth-state
   ```

   Checks again, and returns links to reconnect.

![The «Machine» screen: processor, memory and disk](TODO-shot: machine, overview, demo office, desktop 1440x900, light theme)

## How to check it worked

- `./bbox verify` exits with code 0.
- `./bbox status` shows no container down.

## What not to do when something is down

- No `./bbox reset`. It deletes all the data.
- No direct `docker compose`. See [What not to do](/en/admin/never-do).

## A laptop that runs an office

```bash
./bbox host-power status
```

Says whether the computer is set not to sleep and not to overheat. The install (`install`) requires `sudo`.

## See also

- [Self-healing](/en/apps/autoheal): what the office restarts by itself, and what not
- [What not to do](/en/admin/never-do)
- [The command line](/en/reference/cli)
