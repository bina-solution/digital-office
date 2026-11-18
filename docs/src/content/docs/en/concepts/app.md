---
title: App
description: What an app in the office is — one folder with an app.json — which layer it lives in, and the four ways to reach it.
---

## The problem

Dozens of apps run in the office. Without one concept that defines what an app is, you cannot know where it is written, how to turn it on, or how to talk to it.

## The idea

### One folder, one file

An app is one folder with an `app.json` file. The file says who it is, what it gives other apps, what it needs from them, and at which addresses it opens. The folder may also hold:

- `AGENT.md`: the brief the office's agent reads in order to work in the app.
- `hooks/`: the app's commands. Each file there is a verb.

### The folder is the layer

| Layer | Folder | What it holds |
|---|---|---|
| 0 | `platform/` | The compiler, which turns the declarations into a running office |
| 1–2 | `platform-base/` | What every office gets: the sign-in, the centre, the connections, app management, backup |
| 3 | `apps/` | The business's apps, for example «Files» and «Mail» |

An app in layer 3 does not touch another app directly. It asks for a capability, and the compiler finds it an app that gives it.

### Four ways to reach it

| Way | What it is | Where it is declared |
|---|---|---|
| Screen | A tile in the centre, and the app at the address `/a/<app>/` | `routing` in `app.json` |
| Command line | `./bbox <app> <verb>` runs `hooks/<verb>` | A file in the `hooks/` folder |
| API | The app's actions over HTTP | `capabilities` in `app.json` |
| Event stream | What happened, the moment it happened: `./bbox <app> flow` shows the latest events and stays open | `hooks/flow`, and the stream `dgo:flow:<app>` |

The first three are someone asking. The fourth is the app telling, so that agents and automations listen instead of asking again and again.
Not every app has all four today. [The architecture](/en/architecture) counts how many each one has.

### On or off

`platform.state.yaml` says which apps are on in the office. You turn them on and off from the «App Management» screen, or with a command:

```bash
./bbox apps enable drive
./bbox apps disable drive
```

The data of an app that was turned off is kept.

## What this makes possible

- You find every app in the same place, in the same shape: `apps/<app>/app.json`.
- What you do on a screen you can also do with a command and in code. That is also how the office's agent works in an app, like a person.
- A new app is a new folder. The compiler finds it an address, a sign-in and secrets.

## Going further

- [The concepts](/en/concepts)
- [Office](/en/concepts/office)
- [Turn an app on and off](/en/use/add-app)
- [The architecture](/en/architecture)
