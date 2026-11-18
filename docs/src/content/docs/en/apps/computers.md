---
title: Computers
description: "The app of the computers the office works on: live state, a command and a terminal on a computer, moving data between computers, and what is not locked yet."
---

## What it is

«Computers» (`computers`) holds the list of computers the office can work on, and shows the live state of each: name, operating system, load, memory and disk. It is for administrators only, off in a new install, and is in the «Computers» tile in the «Infrastructure» group.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings the app up:

```bash
./bbox apps enable computers
./bbox run
```

The computer the office runs on is always in the list, and cannot be deleted. A computer you add is kept as a [connection](/en/concepts/connection), so the list stays even when the app is rebuilt.

## Add a computer

The office has an SSH key of its own. The app created it, and it is not your key. A computer is useful only after the public part of this key goes into its `authorized_keys` file.

1. On the «Computers» screen, add a computer. The screen shows the office's public key and the command that copies it.
2. Run the command on the computer you are connecting to, as the user you connect with.
3. Go back to the screen and click «Check now».

Adding and deleting a computer are the office owner's decision. An agent does not add or delete a computer, or replace its key, by itself.

## From the command line

| Command | What it does |
|---|---|
| `./bbox computers list` | Every computer, with each one's id |
| `./bbox computers status <id>` | The live state of one computer. `local` is the computer the office runs on |
| `./bbox computers exec <id> -- <command>` | Runs one command on the computer and exits with its exit code |
| `./bbox computers ssh <id>` | A terminal on the computer, with the office's key |
| `./bbox computers add <host>` | Adds a computer. A key passes only from a file, never as an argument |
| `./bbox computers rm <id> --yes --reason "<why>"` | Forgets a computer and its stored key |
| `./bbox computers transfer <from> <to> <volume>` | Copies a data volume between two computers, and a copy that was cut off can be resumed |
| `./bbox computers audit <id>` | A computer's security findings: SSH, firewall, updates and open ports |
| `./bbox computers flow` | Every command run on a computer of the office: on which computer, who asked, and the exit code |

On the screen itself, «Terminal» on a computer's row opens a terminal on it.

## Computers of linked offices

A [linked](/en/concepts/link) office can give its computer. It appears in the list as `computer_local-local.<office>`. A command to it passes through the link, and the other office runs it with its own key and under its own check.

`./bbox computers herd` compares every office in the [herd](/en/concepts/herd) to the plan: what runs where, what should move, and what runs twice.

## What does not work yet today

- **A command from an unrecognised caller passes.** The default is «warn»: a write from someone the app does not recognise is counted but not blocked, except on computers defined as locked. `./bbox computers callers` shows what was counted.
- **Reading is open to whoever calls.** The check of who is calling applies only to writes. A linked office that reads the list of computers through the link sees the whole list, not only the computer given to it.
- **When the vault does not answer in time,** `ssh` fails with an error about a computer called `none`, instead of saying the vault did not answer. Usually a retry works.
- **A command that waits for input** (a password, a question, an interactive terminal) through `exec` is stuck until its time runs out. That is what `ssh` is for.
- **An empty list does not always mean there are no computers.** When the connections app does not answer, the list looks empty. The message says the reason.
- **Moving data** needs room on the target computer for twice the size of the data, and only one move runs at a time. A second move is refused with the name of the first.

## How to check it works

- `./bbox computers list` shows at least the computer the office runs on.
- `./bbox computers status local` returns name, load, memory and disk.

## Going further

- [Connections](/en/apps/connections)
- [Link](/en/concepts/link)
- [Herd](/en/concepts/herd)
- [Machine](/en/apps/machine)
