---
title: Updating the office
description: "How an office gets a new version by itself: what to declare in .env, what happens in each cycle, how it goes back when something breaks, and what holds an update back."
---

## The problem

An office does not update itself unless it is told to. Without a declaration, it stays on the version that was installed, and every new screen, for example «Connect Google Drive» in [Files](/en/apps/drive), does not reach it.

## The declaration

In `.env`:

| Line | What it says |
|---|---|
| `DGO_FOLLOW` | The branch the office follows. Empty: the office does not update by itself |
| `DGO_BRANCH` | The office's own branch |

**An office installed from the public version** follows nothing by itself: the install leaves both lines empty. For it to update, write `DGO_BRANCH=main` and `DGO_FOLLOW=main` in `.env`, and run `./bbox run`. From then on, every new public version is taken, run and checked, and nothing is pushed back.

`./bbox run` (without an app's name) installs the computer's timer according to the declaration, on two conditions: the computer has systemd, and `bbox` runs as root or with sudo without a password. If not, it says that the office does not follow, and installs nothing. In that case, turn on `follow-runner` (below).

## One cycle

About every 30 minutes after the previous cycle finished (plus up to 5 random minutes), and 15 minutes after the computer started, one cycle runs. It makes at most one change:

1. **Only when it can:** one at a time, not next to other heavy work, not when the computer is loaded, and not when an app says it is in use (for example a meeting that is running).
2. **Takes the version,** and runs `./bbox run`.
3. **Checks:** every service that was running and healthy before the update must run and be healthy after it.
4. **If not:** goes back to the previous version, runs `./bbox run` again, and will not try this version again until a newer one exists.

Every failure reaches [Notifications](/en/apps/notifications) in one line, and is closed when the next cycle succeeds.

## From the command line

| Command | What it does |
|---|---|
| `./bbox follow status` | What is declared, where the office stands, and what happened in the last cycle |
| `./bbox follow --dry-run` | What the cycle would do now |
| `./bbox follow` | One cycle, now |
| `./bbox follow clear` | After you fixed a stopped update by hand: forgets it and keeps following |

## An office without a computer timer

When the office runs only inside containers, and has no computer timer, turn on «Following the stable version» (`follow-runner`). It runs each cycle in a container of its own:

```bash
./bbox apps enable follow-runner
./bbox run
```

## What holds an update back

- **A change by hand in a file the new version changes,** or a change waiting for a commit. The update is put off before anything moves. Such a file that nobody touched for 6 hours is saved in a commit of its own on the office's branch, and the update continues. A file touched recently may be in the middle of work, so the update is put off.
- **A file the version adds that already exists in the folder** without being tracked by git.
- **The folder is not on the office's branch,** or its branch has diverged from the server's branch.
- **A loaded computer.** A cycle is put off when the load is above the number of processors. An office that is loaded all day declares a limit of its own in `DGO_FOLLOW_MAX_LOAD`.
- **An update that stopped halfway** with the code moved on above it. Following stops until `./bbox follow clear`.

## What does not work yet today

- **A change in a Dockerfile does not reach a running office.** The update brings the service up again from the old image.
- **On a small computer the update is very heavy.** On a server with 2 processors the load rose to around 20 during an update.

## Going further

- [Is the office healthy?](/en/admin/health)
- [Notifications](/en/apps/notifications)
- [Declaration](/en/concepts/declaration)
