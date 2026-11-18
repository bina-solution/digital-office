---
title: Link
description: An encrypted connection between two offices — how to link, what goes through it, and what a linked office can do.
---

## The problem

Two offices on two computers do not see each other. To open an app that runs on another computer you need an encrypted path between them, and both sides need to agree on it.

## The idea

### An encrypted tunnel

A link is an encrypted WireGuard tunnel between two offices. A network that blocks UDP blocks WireGuard too. When that happens (measured on Windows/Hyper-V), the pair moves to a TCP path.
Links are managed by the «Office extension» app (`dgo-extend`).

### Three ways to link

- **From the screens:** a QR code, the camera, or an offer pasted as text. Both screens show the same six digits, so both sides know they are linking with each other.
- **A declaration about a computer:** an office installs another office on a computer it reaches over SSH.
- **Joining by declaration (`DGO_JOIN`):** for an office nobody sits in front of.

### What a linked office can do

An app that runs in one office opens as a tile in the centre of another office, without running again. For example, the projects app runs on one computer and opens from the centre of another.

| Command | What it shows |
|---|---|
| `./bbox remote` | The apps of a linked office |
| `./bbox dgo link status` | This office's links: what is declared, and what runs now |

### A limit

A link to an office on a computer that sleeps or is off does not work until the computer is back. A link that dropped and does not come back by itself when the computers are on the same network again is a fault, not a normal state.

## What this makes possible

- You run open source on any computer you have, and reach it from anywhere.
- Several offices become one [herd](/en/concepts/herd).
- `./bbox dgo link history` shows every change of every pair: when the link held, and when it was fixed.

## Going further

- [Herd](/en/concepts/herd)
- [The concepts](/en/concepts)
- [The architecture](/en/architecture)
