---
title: Requirements
description: What the computer needs before you install the office — Docker 28, memory, disk, and what is not supported.
---

## In short

| Requirement | What you need |
|---|---|
| Docker | Version 28 (tested and pinned). |
| Linux | Debian or Ubuntu. Ubuntu 26.04 (kernel 7.0.0-42 or later) needs a fix, see below. |
| macOS | macOS 13 or later. |
| Windows | WSL2. |
| Network | Access to the image registries: Docker Hub and GHCR. |

## Docker 28

Every install of the office installs Docker 28.5.2 and pins it.

**Ask the engine, not its version.** The edge router (`traefik` 3.3) talks to the engine as an API 1.24 client. An engine that does not answer such a client leaves the router with no routes at all: it starts, reports that it is healthy, and every address returns 404, with no error message. On Docker 29, set `DOCKER_MIN_API_VERSION=1.24` and it works: Docker 29.3.1 passed the baseline check that way.

- On macOS and on Windows, the office installs its own Docker 28. There is nothing to do.
- On Linux, check the version before you install:

```bash
docker version
```

`./bbox install debian` checks the version: if a Docker other than 28 is installed, it stops and says so. To replace it (the containers stop, the data is kept):

```bash
BBOX_REPLACE_DOCKER=1 ./bbox install debian
```

## Memory and disk

- **A Mac with 8 GB:** measured. The virtual machine gets 5 GiB and 4 processors. The first warm run took about five minutes, and 33 of 33 services were healthy.
- **Guidance for a future Mac package:** the macOS specification gives 24 GB as the minimum and 32 GB as comfortable, from the memory limits of all the services together.
- **A Linux server, measured:** an office of 60 containers runs on 2 processors and 8 GB of memory with swap, and takes about 44 GB of disk. Leave about 60 GB free (an estimate, not a measurement). An office with fewer apps needs less. Windows has no number of its own measured.
- **First build:** the office builds its images on the first run. On a small computer this takes 10 to 15 minutes. Later runs use the cache.
- **Android:** the app needs 10 GB free on the phone.

## Ubuntu 26.04

On kernel 7.0.0-42 and later, `postgres` does not start because of AppArmor.
To check:

```bash
./bbox apparmor status
```

To fix it (this changes the computer's policy, and the computer's owner decides on it):

```bash
sudo ./bbox apparmor install
```

## A Linux laptop

A laptop can overheat, sleep or freeze. `./bbox run` says so when it finds a battery. To check:

```bash
./bbox host-power status
```

## See also

- [Start — choose a computer](/en/start)
- [Install on Linux](/en/start/install/linux)
