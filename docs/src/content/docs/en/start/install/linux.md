---
title: Install on Linux
description: Bring an office up on Debian or Ubuntu — git clone, the dependencies, a .env file, and ./bbox run.
---

## Why

On Linux the office runs directly on the computer's Docker, with no virtual machine.

## Before you start

- A computer or server with Debian or Ubuntu, and `sudo` rights.
- [The requirements](/en/start/requirements): if Docker is already installed, it must be version 28.
- The public repository is `bina-solution/digital-office`.

## The steps

1. Clone the repository and go into its folder:

   ```bash
   git clone https://github.com/bina-solution/digital-office
   cd digital-office
   ```

2. Install the dependencies: `git`, Docker and what the office needs.

   ```bash
   ./bbox install debian
   ```

   The script `./debian-install.sh` does the same. It installs Docker 28.5.2 and pins it, and creates `.env` from the template `.env.ex` (an existing `.env` is left as it is).
   If it added you to the `docker` group, sign out and in again before the next step.

3. Edit the settings file `.env`. The template says there is one line to edit: `BUSINESS_NAME`, the name of the business. Everything else is derived from it: the office's name, the domain and every address.

   ```bash
   BUSINESS_NAME=MyOffice
   ```

   `DEPLOYMENT_NAME`, `DEPLOYMENT_DOMAIN` and the `*_BASE_URL` values are not edited by hand: they are derived.
   Your own domain: the `COMPANY_BASE_DOMAIN` line. The template reminds you that a domain also needs DNS records.

   **No domain (a laptop, a trial)? A local office.** In step 2 run `DGO_LOCAL=1 ./debian-install.sh`, which does not copy a `.env`, and skip this step. Then `./bbox run` creates a local office by itself: every app at `<app>.localhost`, and the centre at `http://console.localhost`. If the computer already has containers or volumes of the office from this folder, it refuses and says why. If `BUSINESS_NAME` is empty in an office with a domain, `./bbox run` refuses and says in one line what to write.

   You do not need to write the secrets (passwords, keys): the first run of `./bbox run` fills them in, as long as the computer has no data of the office.

4. Bring the office up:

   ```bash
   ./bbox run
   ```

   The command compiles the declarations and brings up every service. On the first run it builds the images, which takes 10 to 15 minutes on a small computer.
   On a new office it prints a line that starts with `[forward-auth] first run: open`, with a one-time link that creates the first administrator. See [After the install](/en/start/after-install).

**Do not run `docker compose` directly.** The `compose.yml` at the root declares only the network. `docker compose up -d` finds zero services and finishes successfully, having done nothing. Use `./bbox run`.

## How to check it worked

```bash
./bbox status
```

The command shows the containers, `n8n` and the permissions. A stricter check, which exits with an error if something is broken:

```bash
./bbox verify
```

![The first screen of a new office after an install on Linux](TODO-shot: the /setup card on a new demo office on Linux; desktop 1440x900, light theme)

## If something does not work

- **Every address returns 404, and everything is "healthy":** check the Docker version (`docker version`). The tested version is 28; according to the repository's documentation, this is what can happen on 29.
- **`postgres` does not start on Ubuntu 26.04:** `./bbox apparmor status`, see [Requirements](/en/start/requirements).

## What next

- [After the install](/en/start/after-install)
- [The first hour](/en/start/first-hour)
