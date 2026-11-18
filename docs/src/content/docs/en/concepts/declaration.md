---
title: Declaration
description: How two files — each app's app.json and the office's platform.state.yaml — become running services, and why what is generated from them is not edited.
---

## The problem

Whoever wires services by hand, with addresses, sign-ins, secrets and a start order, gets a system nobody knows how to build again. And whoever changes what runs by hand loses the change on the next run.

## The idea

### What should run is written in files

- **`app.json`**, one for each app: who it is, what it gives, what it needs, and at which addresses it opens. Its contract is `platform/schema/app.schema.json`.
- **`platform.state.yaml`**, one for the office: which apps are on in it. The product's default is `platform.state.default.yaml`, with 17 apps on.
- **`.env`**: the office's settings and secrets.

### The compiler builds what runs from them

`./bbox run` runs the compiler, `platform/manager/reconcile.py`. The compiler:

1. Reads every `app.json` and the office's state.
2. Checks every declaration against the contract.
3. Resolves: which apps are on, which app gives each capability another needs, and in what order they start.
4. Writes the result to the `.generated/` folder. Docker Compose runs what is written there.

Three commands show the work without running the office:

| Command | What it does |
|---|---|
| `./bbox reconcile validate` | Checks every `app.json` against the contract |
| `./bbox reconcile plan` | Shows what will be resolved and what will change, without writing |
| `./bbox reconcile render` | Writes `.generated/` only |

### Do not edit `.generated/`

The folder is written again from the declarations on every run. A change made in it by hand is erased on the next run.
Make the change in the declaration: in `app.json`, or in a decision about an app (`./bbox apps enable` and `./bbox apps disable` write to `platform.state.yaml`).

## What this makes possible

- The same declarations on any computer build the same office.
- You see what depends on what without reading code, because the capabilities an app gives and needs are written in its file.
- You can check a change before it runs: `validate` and `plan` do not touch the office.

## Going further

- [App](/en/concepts/app)
- [Office](/en/concepts/office)
- [The architecture](/en/architecture)
