---
title: DGO — the digital office
# Starlight appends the site's name to every <title>; on the home page that doubled it («X | X»). Only the tab's title:
head:
  - tag: title
    content: DGO, the digital office — documentation
description: DGO is an open-source operating system for a business's office. It runs the office's apps on your own computers, from declarations.
---

DGO, «the digital office», is an operating system for a business's office.
It runs the office's apps as containers, on a computer of yours.
Every app is declared in one file, and the system builds what runs from it.

![A demo office's centre: the home screen with a tile for each app](TODO-shot: the centre (console), the home screen with the tiles; desktop 1440x900, light theme)

## What the office has

- **The centre**: the screen that holds all the office's apps, each as a tile.
- **One sign-in** for every app.
- **Automations** with `n8n`, and intake of Hebrew financial documents with text recognition.
- **Files, mail, chat, task management** and more apps, turned on and off as needed.
- **An office agent**, «Bina», that acts in the apps you turned on.
- **Several computers, one office**: linked offices open each other's apps.

## How to install

The install: `git clone https://github.com/bina-solution/digital-office`, then one or two commands depending on the computer:
- On Linux: `./bbox install debian`, then `./bbox run`.
- On macOS: `./bbox run`.
- On Windows: `bbox.cmd install windows`, then `bbox.cmd run`.

![Four doors from the home page: what DGO is, start, the concepts, several computers — one office](/diagrams/four-doors.svg)

## Where to start

- [What DGO is](/en/what-is-dgo): what the office runs for you, and what not.
- [Start — choose a computer](/en/start): which computer, which skill, and how to install.
- [The concepts](/en/concepts): the office's words, each once.
- [Several computers — one office](/en/idea): the idea, layer by layer.

DGO is open source under the AGPL licence.
