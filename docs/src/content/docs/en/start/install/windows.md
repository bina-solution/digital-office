---
title: Install on Windows
description: Bring an office up on Windows — WSL, git clone, bbox.cmd install windows and bbox.cmd run. The office runs inside WSL with its own Docker, not with Docker Desktop.
---

## Why

The Docker engine runs only on Linux. On Windows, WSL2 is the Linux.
The office installs its own Docker CE, version 28, inside WSL.
Docker Desktop is not used, whether it is installed or not.
This is the only way to run the office on Windows.

## Before you start

- Windows with WSL2 and the `Ubuntu` distribution. Once per computer: open PowerShell as administrator and run the command below, restart the computer, and open Ubuntu once.

  ```
  wsl --install -d Ubuntu
  ```

- `git` on Windows.
- An ordinary command line: `CMD` or PowerShell.

## The steps

1. Clone the repository into any folder on the `C:` drive and go into it:

   ```
   git clone https://github.com/bina-solution/digital-office C:\path\you\like\digital-office
   cd C:\path\you\like\digital-office
   ```

2. Prepare WSL for the office:

   ```
   bbox.cmd install windows
   ```

   The command prepares WSL and installs `git` and Docker inside it. It may ask for `wsl --shutdown` and a second run of itself.

3. The settings file `.env` is yours, as on Linux: see [Install on Linux](/en/start/install/linux), step 3.

4. Bring the office up:

   ```
   bbox.cmd run
   ```

   `bbox.cmd` passes the command to the `bbox` inside WSL's `Ubuntu` distribution, on exactly the same folder. There is no second copy to keep in sync.
   On `run` it also registers a scheduled task in Windows (Task Scheduler) that keeps WSL awake, so the office comes back by itself after a restart.

## How to check it worked

```
bbox.cmd status
```

WSL2 forwards `localhost`, so the edge inside WSL answers the Windows browser directly. If the addresses in `.env` are `*.localhost`, open `console.localhost`.

> TODO-product: the address of a Windows office. The template `.env.ex` derives `console.<slug>.digital-office.co.il`, not `*.localhost`, and no source says how a Windows office without a domain opens in the browser.

![A CMD window with bbox.cmd run halfway through](TODO-shot: a CMD window on Windows, bbox.cmd run halfway through; light theme)

## If something does not work

- **`Error code: Wsl/Service/0x8007274c`:** Windows did not get an answer from the WSL machine in time, usually under heavy work. This is not a fault in the office. Try again.
- **Windows is left without memory after heavy work:** WSL does not give memory back by itself. `wsl --shutdown` gives it back at once, but stops everything running in WSL, the office included. Do it only between jobs.

## An office another office calls

In WSL's usual network mode (NAT), nothing on the network reaches the office. It can only call out.
For another office to call it, you need the `mirrored` network mode, on Windows 11 22H2 or later:

```
bbox.cmd dialable -Check
bbox.cmd dialable
bbox.cmd dialable -Undo
```

The first only reads. The second explains what it will do and asks for a typed `YES`. The third returns the previous mode. The switch restarts WSL.

## What next

- [After the install](/en/start/after-install)
- [The first hour](/en/start/first-hour)
