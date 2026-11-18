---
title: Database
description: "The office's Postgres: what is kept in it, why it is called supabase-db, who holds a database of their own, and how to back it up."
---

## What it is

«Database» (`postgres`) is the office's database: Postgres 15. It is part of the base of every office (layer 1), and has no tile. Apps that hold data write to it, for example [INDOX](/en/apps/indox) (each instance in a schema of its own), the document ledger of [API Tools](/en/apps/apitools), [Chat](/en/apps/chat), and «Office storage», the engine of [Files](/en/apps/drive).

## Why it is called `supabase-db`

It was once part of the Supabase app. Today the office provides a database, not Supabase: the other parts of Supabase moved to a separate app, `supabase`, which can be added. The name `supabase-db` and Supabase's image stayed, because every database address in the office already points at them. An app that talks to the database sees no difference.

## Who holds a database of their own

Not every app writes here:

| App | Its database |
|---|---|
| [Automations](/en/apps/n8n) | `n8n-postgres`, its own |
| [Projects](/en/apps/project-pln) | `plane-db`, its own. It is not connected to the office's database |
| authentik (when it is turned on) | `authentik-postgres`, its own |
| Error tracking (when it is turned on) | `glitchtip-postgres`, its own |

Port 5432 of the [edge router](/en/apps/traefik) belongs to n8n's database, not to this one.

## Backup

`./bbox export` keeps it with the office's other data, and `./bbox import` brings it back. See [Backup](/en/backup) and [Data management](/en/apps/data-management).

**A copy of the folder does not back it up.** The data is in the engine's volume, outside the folder.

## What does not work yet today

- **On Ubuntu 26.04, on kernel 7.0.0-42,** the database does not start: the computer's AppArmor prevents the processes inside the container from sending signals to each other. `./bbox apparmor status` checks whether your computer is in that state. `./bbox apparmor install` installs a profile that solves it without weakening the computer. It is an action for the owner, with `sudo`. The fault is still open.

## Going further

- [Backup](/en/backup)
- [Data management](/en/apps/data-management)
- [Edge router](/en/apps/traefik)
