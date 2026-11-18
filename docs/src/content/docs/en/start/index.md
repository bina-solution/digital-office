---
title: Start — choose a computer
description: Choose the computer the office will run on. Each choice says what skill and what computer it needs.
---

## Why

The office runs on Linux, on macOS and on Windows.
On every computer it is a `git clone` of the public repository and one or two commands.
What differs is the engine that runs the containers.

## Before you start

Read [the requirements](/en/start/requirements). The one that matters most: Docker version 28. On Linux, the installer installs it for you.

![A card for each system: Linux, macOS, Windows, Android — the skill, the computer and the command](/diagrams/install-chooser-cards.svg)

## The choices

### Linux (Debian or Ubuntu)

- **Computer:** a server or a computer with Debian or Ubuntu.
- **Skill:** working in a terminal, `sudo`, and editing a settings file.
- **Commands:** `./bbox install debian`, then `./bbox run`.
- [Install on Linux](/en/start/install/linux)

### macOS

- **Computer:** a Mac with macOS 13 or later. The office runs its own virtual machine, with no Docker Desktop and no administrator rights.
- **Skill:** working in a terminal. The settings file is created by itself on the first run.
- **Command:** `./bbox run`.
- [Install on macOS](/en/start/install/macos)

### Windows

- **Computer:** Windows with WSL2. The office installs its own Docker inside WSL and does not use Docker Desktop.
- **Skill:** a `CMD` or PowerShell command line. If WSL2 is not installed yet, there is one step with administrator rights and a restart.
- **Commands:** `bbox.cmd install windows`, then `bbox.cmd run`.
- [Install on Windows](/en/start/install/windows)

### Android

What exists today: a draft APK, under 2 GB, not in the store. The first start is about 20 times slower than on a computer, because the processor is emulated. The Android install page is not written yet.

### With an agent

A coding agent running on your computer can run the install: the one command `curl -fsSL https://digital-office.co.il/install.sh | bash`, or the Claude plugin. The password and the first sign-in stay yours.

- [Install with an agent](/en/start/agent-prompt)

## How to check it worked

Every install page ends with how to check. On every computer, `./bbox status` (on Windows `bbox.cmd status`) shows the state of the containers.

## What next

- [Requirements](/en/start/requirements)
- [After the install](/en/start/after-install)
