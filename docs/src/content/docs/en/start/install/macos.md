---
title: Install on macOS
description: Bring an office up on a Mac — git clone and ./bbox run. The office sets up its own virtual machine with Docker 28, with no administrator rights and no Docker Desktop.
---

## Why

A Mac has no Linux kernel, and Docker needs one.
So `bbox` sets up an engine of its own: an Ubuntu virtual machine (Lima on Apple's Virtualization.framework) with Docker CE 28.5.2 pinned to that version.
Everything is created in the folder `~/.bbox/macos`, with no administrator rights, no Docker Desktop and no Homebrew.

## Before you start

- macOS 13 or later.
- Clone the repository into any folder under your home folder. The engine sees the folder at the same path.
- A browser: Chrome or Firefox. Safari before macOS 26 does not find `*.localhost` addresses.
- Images built only for amd64 need Rosetta. Apple installs it:

  ```bash
  softwareupdate --install-rosetta
  ```

- [The requirements](/en/start/requirements): on a Mac with 8 GB, the machine gets 5 GiB and 4 processors.

## The steps

1. Clone the repository and go into its folder:

   ```bash
   git clone https://github.com/bina-solution/digital-office
   cd digital-office
   ```

2. Bring the office up:

   ```bash
   ./bbox run
   ```

   On the first run `bbox` downloads a pinned, verified version of Lima, sets up the machine, and passes the command to it.
   `./bbox install macos` and `./bbox engine start` set up only the engine. `./bbox run` sets up the engine and brings the office up.

3. No `.env` file? The first run creates one: random secrets, `DEPLOYMENT_NAME=local`, and the edge on port 8080.
   Then write the name of the business in it, `BUSINESS_NAME`.

The office's addresses are `http://<app>.localhost:8080`. On macOS a process without privileges cannot open port 80.

**If you wrote `.env` by hand:** every address the browser opens (`*_BASE_URL`, `AUTH_EXTERNAL_URL`) must include `:8080`. Without it every app behind the sign-in returns 404, and `bbox status` still shows everything green.

## How to check it worked

```bash
./bbox engine status
./bbox status
```

Measured on a Mac with 8 GB: the first warm run took about five minutes, and 33 of 33 services were healthy.

![The output of ./bbox engine status in a Mac terminal](/shots/macos-engine-status.light.he.png)

## The engine

| Command | What it does |
|---|---|
| `./bbox engine start` | Starts the engine |
| `./bbox engine stop` | Stops the engine |
| `./bbox engine status` | The engine's state |
| `./bbox engine shell` | A terminal inside the machine |
| `./bbox engine doctor` | Checks the engine |

Note: `./bbox engine shell` starts a stopped engine. Check `./bbox engine status` first.

## Sleep and the lid

A Mac that sleeps freezes the machine and everything in it.
The console's settings («Console settings…») have a «Power and sleep» card: for each state (screen locked, lid closed) and each power source, «keep working» or «sleep».
With the lid closed, a Mac sleeps anyway, unless the computer's owner installs the narrow rule the card shows. Without that step: power plus an external display keep a closed Mac working.

## What next

- [After the install](/en/start/after-install)
- [The first hour](/en/start/first-hour)
