---
title: Office extension
description: "The app that links offices: a linked office and an office installed from here, what passes through the link, whether it is alive, moving an app, and what does not come back by itself."
---

## What it is

«Office extension» (`dgo-extend`) manages the [links](/en/concepts/link) between this office and other offices. It is for administrators only, off in a new install, and is in the «Office extension» tile in the «Infrastructure» group. On the command line its name is `dgo`.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings the app up:

```bash
./bbox apps enable dgo-extend
./bbox run
```

## Two kinds of linked office

| Kind | What it is | Who runs it |
|---|---|---|
| Linked | An office installed on a computer of its own and linked from the «Join an office» screen | Itself. From here it is not installed and not reached over SSH |
| Declared | A computer from [Computers](/en/apps/computers) that this office installs, by a declaration: computer, domain, folder, version and apps | This office, over SSH, in fixed stages |

## What passes through the link

- **What this office gives.** For each link, the apps the office gives are defined, and the link's door answers only for them. When nothing is chosen, a new link gives all the office's apps. The administration apps are not given this way to an unfamiliar office, only when they are chosen by name.
- **In whose name.** A request that passes through the link reaches the app in the name of this office's user.
- **What it sees of others.** Every 60 seconds it reads from every linked office its list of apps. Each of them opens in the centre as a tile named `<alias>.<office>`. An office that did not answer keeps its last list, marked as not answering.

## Is the link alive

Every linked office has one answer: alive, or where it stopped.

| Where it stopped | What it means |
|---|---|
| `tunnel` | No handshake in the tunnel, or nothing was measured. What was not measured does not count as alive |
| `office` | The tunnel is alive, but the office on the other side does not answer |
| `door` | The link's door is not listening here |
| `pair` | This office dials a private address on a network it is not on. It needs to be linked again |

The centre marks that office's tiles by this answer.

## From the command line

| Command | What it does |
|---|---|
| `./bbox dgo` | This office and the offices linked to it |
| `./bbox dgo link status` | For each link: tunnel, handshake, door and list of apps |
| `./bbox dgo link history` | Every change of every link: when it held, and who fixed it |
| `./bbox dgo link up <office>` | Brings up a link to a declared office. `down` takes it down |
| `./bbox dgo identity fingerprint` | Who this office is. The identity is kept in the backup |
| `./bbox remote <office> <alias>` | The doors of an app in a linked office |

A link to a linked office is disconnected from its screen, not by a command from here.

## Move an app to a linked office

From the apps screen. The receiving office is asked whether it has room, pulls the data through the link and brings the app up. Only then is the app turned off here. Nothing is deleted.

## Install a declared office

The install goes through fixed stages, and each stage can be followed:

1. **Backup** of what is already on the computer: the databases, the volumes and `.env`. The last three backups are kept. When there is no room, the stage is skipped.
2. **Code:** the version in the declaration. A change made there by hand is kept aside, not deleted.
3. **Engine:** Docker version 28.5.2, pinned. See [Requirements](/en/start/requirements).
4. **Settings:** an existing `.env` only grows. A secret that already exists is not created again.
5. **Apps:** the declaration is all of that office's apps. What it does not mention is turned off.
6. **Run and check:** `./bbox run`, then a check that the version, the services and the centre answer.

The version in the declaration must already be on the code server, because the computer pulls it from there. Deleting a declaration does not touch the computer, its files or its data.

## What comes back by itself, and what not yet

A link that dropped repairs itself in two ways: a new port in place of a port blocked by a home router, and a search for the address that moved on the local network, which accepts only a completed handshake.

**What does not come back by itself yet:**

- **A link written the wrong way round** (the answer `pair`): there is no fix from this side. Link again.
- **A link's record that disappeared:** nothing detects it, and there is no fix.
- **A public address that changed:** the address is set when the link is written, and nothing checks it again.
- **A declared office after a restart** gives nothing until the office that installed it runs the link stage again.
- **A new office** cannot be linked after its first run: its identity is created only on the second run, or with `./bbox dgo identity mint`.

By the project's rules, a link that does not come back by itself is a fault, and each of these is recorded as a fault, open or being handled.

**What is not locked yet:**

- **A linked office acts as the owner.** Since a request from a link arrives in the name of the office's user, whoever controls one office acts as the owner in every app given to it in the linked office.
- **A service inside the office's network** can use the link's door directly, and the request is signed in the office's name.

Both faults are open. Until they are closed, give through a link only the apps that are needed.

## Going further

- [Link](/en/concepts/link)
- [Herd](/en/concepts/herd)
- [Computers](/en/apps/computers)
- [Console (the centre)](/en/apps/console)
