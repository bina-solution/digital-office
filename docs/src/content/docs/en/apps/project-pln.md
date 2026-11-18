---
title: Projects
description: "Plane on the office's server: projects and work items, one sign-in with the office, work from the terminal — and what does not work yet."
---

## What it is

«Projects» (`project-pln`) is Plane Community Edition running on the office's server: a workspace holds projects, and a project holds **work items**, by states, labels and modules. It is in Hebrew and right to left. It is off in a new install, and is in the «Projects» tile in the «Business» group.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings the app up:

```bash
./bbox apps enable project-pln
./bbox run
```

## No setup wizard

Ordinary Plane lets nobody in until someone fills in a setup screen by hand. Here the setup is declared: running `./bbox run` sets up the workspace, the project, the states and the labels, and creates the owner's account.

- **The owner's sign-in** is `PLANE_OWNER_EMAIL` and `PLANE_OWNER_PASSWORD` from `.env`. It is kept in the vault, and can be read in [Connections](/en/apps/connections), on Plane's card. The address must be real: with an example address (like `@example.com` or `@local.dev`), the setup skips Plane and says why.
- **No self-registration.** An open registration form is a machine that produces accounts.
- **Sign-in through the office, for whoever is named.** Whoever's name is written in `sso.users` of `apps/project-pln/bootstrap.yaml` signs in to Plane with no extra form. By default only `akadmin` is written there. Everyone else gets Plane's sign-in form. A linked office signs in through the link, with the link's signature, by the same list.
- **No reporting out.** Plane's reporting to its maker is off in the code, not only in the settings.

## From the command line

| Command | What it does |
|---|---|
| `./bbox project-pln verify` | Checks that it can really be used: the API answers, the setup is in place, and the owner can sign in |
| `./bbox project-pln tasks show <REF>` | One work item |
| `./bbox project-pln tasks start <REF>` | Moves an item into work. Also `done`, `take` and `comment` |
| `./bbox project-pln tasks attach <REF> <file>` | Attaches files to an item |
| `./bbox project-pln plan <name> --dry-run` | What a declared plan would change: project, states, labels, modules and items. Without `--dry-run` it applies. It updates and adds, and deletes nothing |
| `./bbox project-pln import-cloud` | Imports a workspace from Plane Cloud, in two stages. The first stage creates the missing projects, empty, and writes a plan for review. `--apply` moves the items. It needs two tokens: `PLANE_CLOUD_API_TOKEN` and `PLANE_LOCAL_API_TOKEN`. Pages and attachments do not move |

## What does not work yet today

- **A project the plan creates** gets only the owner as a member, not the office's agent. The agent does not see it until it is added.
- **On a phone,** on an item's page, the state, the assignees and the priority appear below the whole description.
- **The owner gets a sign-in form.** In a new office the owner chooses a username of their own on the first sign-in, and that name is not written in `sso.users`. Until it is added there, Plane asks them to sign in with its own form.

## How to check it works

A green container does not say the setup is complete. `./bbox project-pln verify` does: it checks that the owner can really sign in.

## Going further

- [Connections](/en/apps/connections)
- [Video meetings](/en/apps/meet)
- [Identity and sign-in](/en/apps/forward-auth)
