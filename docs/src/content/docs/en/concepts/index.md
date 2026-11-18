---
title: The concepts
description: The office's words — office, app, declaration, herd, link, agent, instance, connection — each once, with an example.
---

## The problem

Whoever comes into the office meets words that recur on every screen and in every command. Here each word is explained once.

![The words in one picture: two offices, apps in layers, declarations, an agent, a connection, a link and a herd](/diagrams/words-on-one-picture.svg)

## The idea, word by word

### Office

One computer that runs DGO, with one `.env` settings file of its own.

### App

One folder with one `app.json` file. Every app belongs to a layer, and the folder is the layer:
- Layer 0, `platform/`: the compiler.
- Layers 1 and 2, `platform-base/`: what every office gets, such as the sign-in and the centre.
- Layer 3, `apps/`: the products, such as «Files».

Every app opens in four ways: a screen (a tile in the centre), a command (`./bbox <app> <verb>`), an HTTP API, and an event stream.
Example: `./bbox drive ls /` shows what is in the top folder of «Files».

### Declaration

What the office should run, written in files: `app.json` for each app, and `platform.state.yaml`, which says which are on.
The compiler reads them and builds `.generated/`. Nobody edits `.generated/` by hand.
Example: `./bbox apps enable drive` writes the decision to `platform.state.yaml`.

### Herd

Several offices, each on a different computer, linked to each other and working as one business.
Each computer in the herd has a role: the desk, «the office», which is always on, the workshop for heavy work, and the window to the public.
Example: `./bbox computers herd` checks what runs on each computer, against what is planned.

### Link

A connection between two offices, through the «Office extension» app (`dgo-extend`).
A linked office opens the other's apps as tiles, without running them again.
Example: `./bbox remote` shows the apps of a linked office.

### Agent

The office's agent, «Bina» (`bina-ds`). It learns every app that is on from its brief, `AGENT.md`, and acts in it.
When an app is turned off, its brief leaves the agent.
Example: `./bbox agent --help` shows how to talk to the agent from the terminal.

### Instance

One office serves several instances. The word is «instance», not «tenancy».

### Connection

A key or a sign-in for an outside service. Connections are kept in the «Connections» app (`connections`), and an app gets permission to use them, not the secret itself.
Example: the key for the language model that «Bina» uses.

## What this makes possible

With these eight words you can read every page of the documentation, every screen and every command of the office.

## Going further

- [Glossary](/en/glossary)
- [What DGO is](/en/what-is-dgo)
- [Several computers — one office](/en/idea)
