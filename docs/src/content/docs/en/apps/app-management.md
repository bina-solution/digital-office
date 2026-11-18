---
title: App Management
description: "The app that manages every app: what is installed, what is on, where each one runs — and what each action keeps or deletes."
---

## What it is

«App Management» (`app-management`) is the office's control centre: which apps are installed, which are on, and where each one runs. It is part of the base of every office (layer 1).
It reads the declarations (each app's `app.json`, and `platform.state.yaml`) and the running containers, and changes state only through the compiler. That way what is written and what runs do not drift apart.

## The screen

In the centre, the «Apps» tile in the «Infrastructure» group. The screen is for administrators only, and has three tabs:

- **«My apps»:** the installed ones. Open, turn off and remove, and see what is declared for each one and what really runs.
- **«App store»:** what can be installed.
- **«Core services»:** the office's infrastructure. They cannot be turned off or removed.

## What each action does

| Action | What happens | What is kept |
|---|---|---|
| Turn on | Writes the decision, prepares the app, brings it up, waits for it to be healthy and connects it to the sign-in | — |
| Turn off | Stops the containers | The data is kept |
| Archive | Removes containers and images | The volumes, that is the data, are kept |
| Remove | Removes the containers and runs the app's own removal cleanup | Depends on the choice: remove with delete deletes every volume of the app |
| Move to another office | The other office checks it has room, takes the data over the link and brings the app up. Only then is it turned off here | Nothing is deleted |

Turning on a large app takes a while. The screen answers at once, and keeps showing the progress to the end.
Turning off an app that another running app needs writes the decision, but leaves it running. The answer says who holds it.

## From the command line

Read only:

| Command | What it shows |
|---|---|
| `./bbox app-management apps` | Every app: what is declared and what runs |
| `./bbox app-management room <app>` | Whether the computer has the processor and memory for it |
| `./bbox app-management job <app>` | The progress or result of the latest turn-on or move |
| `./bbox app-management office` | This office's record |

To change: `./bbox apps enable <app>` and `./bbox apps disable <app>`, followed by `./bbox run`. They write the decision and compile. They do not bring up or stop anything by themselves.

## How to check it works

- The «Apps» tile opens and shows the list.
- `./bbox app-management apps` returns every app.

## Going further

- [Turn an app on and off](/en/use/add-app)
- [App](/en/concepts/app)
- [Declaration](/en/concepts/declaration)
