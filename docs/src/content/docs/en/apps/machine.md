---
title: Machine
description: "The numbers of the computer the office runs on: processor, memory, disk, the containers, what can be cleaned, and the power and sleep policy."
---

## What it is

«Machine» (`machine`) shows the numbers of the computer the office runs on: processor, memory and disk, each container and how much it uses, what takes up the disk, what can be cleaned, and the power policy. It is part of the base of every office (layer 2), and for administrators only.

## Where you see it

It has no tile of its own. Its screen is inside «Computers». The «Power and sleep» card in the centre's settings screen also reads from it and writes through it.

## From the command line

The four commands only read, and change nothing:

| Command | What it shows |
|---|---|
| `./bbox machine overview` | Processor, memory, disk, and how much each container uses |
| `./bbox machine storage` | What takes up the disk: images, volumes, build cache |
| `./bbox machine cleanup-options` | What a cleanup can free, and which actions are allowed in this office |
| `./bbox machine power` | The power policy, and the data of the computer itself |

It is worth running `./bbox machine overview` before a heavy build, to see that there is room.

## Cleanup

A cleanup works on the whole engine: every stopped container, every image not in use, or the build cache.
By default no cleanup action is allowed. The office refuses every cleanup until an administrator allows it explicitly. A deleted image has to be built again, and a stopped container may be someone's work that is waiting.

## Power and sleep

The power policy sets whether the computer may sleep. The default is to keep working.
On a Mac, a computer that sleeps freezes the engine and everything running in it, the agents included.
«Machine» does not shut the computer down and does not restart it.

## How to check it works

`./bbox machine overview` returns the computer's numbers and the list of containers.

## Going further

- [Requirements](/en/start/requirements)
- [App Management](/en/apps/app-management)
- [Is the office healthy?](/en/admin/health)
