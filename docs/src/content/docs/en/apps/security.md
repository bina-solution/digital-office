---
title: Security
description: "Who reaches the office and where it reaches out, and blocking addresses that attack: what the app sees, how it decides, and why it only watches until the owner decides otherwise."
---

## What it is

«Security» (`security`) shows who reaches the office and where the office reaches out, and it has a mechanism that blocks addresses that attack. It is for administrators only, and is in the «Security» tile in the «Main» group.

In the default file it is off. `./bbox onboarding` turns it on by itself on a computer that has a public address. Elsewhere, turn it on from the command line: `apps enable` only writes the decision, and `./bbox run` brings it up:

```bash
./bbox apps enable security
./bbox run
```

It runs in two parts: the screen and the service behind it, which are behind the sign-in, and a sensor that reads the computer's traffic. The sensor has no address that can be reached.

## What it shows

- **Who came in:** a row per address, with the place, the network, the apps opened and the users.
- **Where the office reaches out:** by destination, with the names, who made the call, and whether an app declared that destination.
- **SSH sign-ins:** which keys signed in, and every attempt that failed.
- **What linked offices opened here.**
- **Blocks:** the mode, the rules and the addresses blocked right now.

## From the command line

| Command | What it does |
|---|---|
| `./bbox security summary` | The numbers of the last 24 hours: requests, addresses, blocks and outgoing calls |
| `./bbox security inbound` | Who came in, by address |
| `./bbox security outbound` | Where the office reached out, and who made the call |
| `./bbox security ip <address>` | One address: its requests, sign-ins and blocks |
| `./bbox security bans` | The mode, the rules and the active blocks |
| `./bbox security herd` | The summary of every linked office |
| `./bbox security verify` | The app answers, the sensor writes, and the edge router's log is read |

`summary`, `inbound` and `outbound` take a number of hours.

## How it decides to block

| What counts as an attack | The threshold |
|---|---|
| Scanning: requests that fail, or calls to paths that look for holes, on what is open without a sign-in (a public site, the door of a link, a name nobody routes) | 12 failures, or 3 such paths, in 10 minutes |
| Failed sign-in attempts | 5 in 15 minutes |
| Failed SSH attempts | 5 in 10 minutes |

A request for `/` or for the site's icon that came back 404, on a name nobody routes, does not count as scanning: that is how every browser asks about a name it has not seen.

A first block is for an hour, and every return multiplies it by 4, up to seven days at most.

**Who is never blocked:** private addresses, the office's own addresses, linked offices, an address that signed in successfully in the last 30 days, and what is on the allow list.

## Watching and enforcing

A new office starts **watching**. A decision to block is recorded as «would have been blocked», and nothing is really blocked. The owner switches to enforcing on the screen, in the blocks tab («Switch to enforcing»). An agent does not change the mode.

Outgoing calls are only marked too. A call to a destination no app declared is marked, and not blocked.

From a linked office nothing can be changed here: not blocks, not rules and not the mode, unless this office explicitly allowed it.

## What does not work yet today

- **The apps screen does not turn it on.** An app of the base is turned on today only by command or on the first install.
- **On a laptop it does not see the real address.** There the office runs inside a virtual machine, and the edge router sees the address of the computer itself, not of whoever made the request. On a server it sees the real addresses, except what arrives over IPv6.
- **A visitor over IPv6 looks like the office itself.** On a server with a public IPv6 address, a visitor over IPv6 arrives from an internal address, so they are never blocked. Until this is fixed, close IPv6 for ports 80 and 443 in the server's firewall.
- **Nothing is blocked until the owner switches to enforcing,** and an outgoing call to an undeclared destination is only marked.

## What it downloads from outside

On the first start it downloads a free location database (DB-IP lite, under the CC BY 4.0 licence), to know where each address comes from:

| `SECURITY_GEO` | What is kept | Size on disk |
|---|---|---|
| `city` (the default) | Country, city and network | About 145 MB |
| `country` | Country and network | About 18 MB |
| `off` | Nothing. Nothing is downloaded | — |

## Going further

- [Herd](/en/concepts/herd)
- [Office extension](/en/apps/dgo-extend)
- [What not to do](/en/admin/never-do)
