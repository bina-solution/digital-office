---
title: Containers
description: "The app that holds the office's container engine: what it is, why it is always on, and which engine each operating system has."
---

## What it is

«Containers» (`containers`) is the one app responsible for running containers. Every app that runs in a container needs it, and the office adds it for that app, the way an app with a database adds the database. It is for administrators only, and has no tile.

It runs no container of its own. The engine is the engine of the computer the office runs on.

**It is always on,** as long as the office's state (`platform.state.yaml`) does not say otherwise. On every system except Android, the office's base itself runs in containers, so the engine exists before anything else.

## The engine on each operating system

| System | The engine today |
|---|---|
| Linux | Docker 28.5.2, directly on the computer |
| macOS | Docker inside a Lima virtual machine |
| Windows | Docker inside a WSL distribution |
| Android | Docker in the office's virtual machine |
| iOS | None. The app reaches an office running on another computer |

The databases are kept in volumes on the engine's disk.

## What does not work yet today

- **The engine is pinned to Docker 28.5.2, on every system.** What matters is whether the engine answers a client at API version 1.24, the way the edge router talks. On Docker 29 it works only with `DOCKER_MIN_API_VERSION=1.24`. Without it the router routes nothing, with no message. See [Requirements](/en/start/requirements).
- **Some of the apps' files are still in the office's folder.** On macOS that folder is shared with the computer, so those files are not on the virtual machine's disk. Moving them there is planned work. Only on Android is everything already inside the machine.
- **On Android** the office's base runs without containers, but some of the core apps still start the engine. The next step: the base starts without the engine, and «Containers» is installed only when asked for.

## Going further

- [Requirements](/en/start/requirements)
- [The apps](/en/apps)
- [The architecture](/en/architecture)
