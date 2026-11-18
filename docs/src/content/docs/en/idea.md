---
title: Several computers — one office
description: The idea of the herd, layer by layer — from one computer that runs an office, to several computers working as one business.
---

## The problem

A business does not run on one computer.
There is a laptop that comes and goes, a computer that stays on in the office, a strong computer for heavy work, and a cloud server the public reaches.
When each runs apps of its own, the data scatters, and the same app runs twice.

## The idea, layer by layer

### 1. One computer runs an office

On one computer, `./bbox run` turns declarations into running apps.
The centre shows every app as a tile, with one sign-in.

![One computer: the declarations, the compiler, the engine and the apps, and above it the centre with the tiles](/diagrams/layer-1-one-computer.svg)

### 2. One computer is fragile and small

A laptop sleeps, gets closed, and travels.
An old computer overheats and shuts down.
And one computer has no room for all the work, for example for local models and transcription.

![The same computer with three signs: a closed lid, a thermometer, a full memory bar](/diagrams/layer-2-fragile.svg)

### 3. Link a second office

A second office runs on another computer.
The «Office extension» app (`dgo-extend`) links the two.
Each office opens the other's apps as tiles, without running them again.
From the terminal: `./bbox remote` shows the apps of a linked office, and `./bbox via <office> <bbox args…>` runs a command on the linked office.

![Two computers, an office on each, and a link between them; in the first one's centre, a tile from the second](/diagrams/layer-3-link.svg)

### 4. One sign-in

Every office comes with one sign-in for all its apps (in a new office: `forward-auth`, «Identity and sign-in»).
The sign-in, the edge, the centre, the links, security and the computers are the base that runs on every computer.

![One person, one sign-in card, and behind it all the office's tiles, including tiles of a linked office](/diagrams/layer-4-sign-in.svg)

### 5. Who may reach whom

Only the link passes between offices.
Every office has a «Security» app that records what passes through the door.

![Two offices and one door on the link between them, with the door's log in the security app](/diagrams/layer-5-door.svg)

### 6. What runs where

Each computer in the herd has a role, and every app runs once only:

- **The desk**, the laptop: the interface. The centre, the links and the agent. No business data.
- **«The office»**, a computer that is always on: the centre of the herd. All the business's apps, all the automations (`n8n`), and all the data.
- **The workshop**, a computer for heavy work that runs at times: local models, transcription, text recognition, and the backup copies.
- **The window to the public**, a cloud server: the websites, the meetings, the mail, and the public sign-in for the whole herd.

Three rules: one of everything. The data lives with its app. «The office» is the centre, and every other office talks to it directly.
`./bbox computers herd` checks what runs on each computer, against the plan in the file `apps/computers/herd.yaml`.

![Four computers with the names of their roles; «the office» in the centre and a link from every computer to it](/diagrams/layer-6-roles.svg)

### 7. Several computers, one office

A herd can be several offices: a laptop, a computer that is always on, a computer for heavy work and a cloud server.
Every office talks to «the office» directly.
Not every office is linked to all the others: the public server, for example, needs no path to the workshop.

![Several computers in their roles, linked to «the office», with no link between the public server and the workshop](/diagrams/layer-7-herd.svg)

## What this makes possible

- When the laptop is off or on the road, the business does not stop.
- The business's data is in one place, and the backup copies in another.
- Heavy work does not slow down the computer you work on.

## What is not true yet today

A link that dropped should come back by itself when the computers are on the same network again. Today that does not always happen, and sometimes it has to be brought back by hand.

## Going further

- [The concepts](/en/concepts)
- [What DGO is](/en/what-is-dgo)
- [Glossary](/en/glossary)
