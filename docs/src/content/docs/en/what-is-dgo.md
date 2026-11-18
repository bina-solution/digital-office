---
title: What DGO is
description: What the digital office runs for an office, how it is built, and what it does not do.
---

## The problem

An office uses many apps: files, mail, automations, chat, task management.
Each is installed separately, with its own sign-in and its own upkeep.
Whoever wires them together by hand has to remember how they did it.

## The idea

DGO is the business's digital office: an operating system that runs the office's apps as containers.
Every app is declared in an `app.json` file of its own.
The file `platform.state.yaml` says which apps are on.
The office's compiler reads both and builds what runs from them, in the `.generated/` folder.
Nothing is wired by hand.

The goal: `git clone` followed by `./bbox run` brings up a whole office from the `.env` settings file.

![One computer: the declarations, the compiler, the .generated folder and the engine, and above them the centre with the tiles](/diagrams/office-on-one-computer.svg)

## What runs in the office

The office is built in layers, and the folder is the layer:

- **Layer 0**, `platform/`: the compiler.
- **Layers 1 and 2**, `platform-base/`: what every office gets. The edge (`traefik`), the sign-in (`forward-auth`), the databases (`postgres`, `redis`), the connections to outside services, the centre, app management and more.
- **Layer 3**, `apps/`: the products. One folder and one `app.json` per app. For example: files, mail, chat, INDOX for the intake of Hebrew financial documents, `apitools` for text recognition and PDF.
- **The automations (`n8n`)** are off in a new office. Turn them on as needed.

![A demo office's centre: the grid of apps](TODO-shot: the centre (console), the grid of apps; desktop 1440x900, light theme)

Every app opens in four ways: a screen in the centre, a command `./bbox <app> <verb>`, an HTTP API, and an event stream.

## What this makes possible

- Turn an app on and off with one command: `bbox apps enable <app>` or `bbox apps disable <app>`. The data is always kept.
- One sign-in for every app.
- An office agent that learns every app you turned on from its brief.
- Link an office to another office on another computer, so that it opens the other's apps.

## What DGO does not do

- **It is not fully self-contained.** The settings file holds keys for outside services (for example language models, Google, Telegram), and the public security certificates come from Let's Encrypt.
- **It installs Docker 28.** Its installers install Docker 28.5.2 and pin it. What matters is whether the engine answers a client at API version 1.24, the way the edge (`traefik` 3.3) talks. On Docker 29, set `DOCKER_MIN_API_VERSION=1.24`. Without it the edge finds no route at all, with no error message. See [Requirements](/en/start/requirements).
- **There is no single signed installer.** Installing today is a `git clone`, a settings file and a command.

## Going further

- [The concepts](/en/concepts)
- [Several computers — one office](/en/idea)
- [Start — choose a computer](/en/start)
