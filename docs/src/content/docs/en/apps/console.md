---
title: Console (the centre)
description: "The office's home screen: every app in one place, each at an address of its own, and the one link builder that gives a person a link that works."
---

## What it is

«Console» (`console`), the centre, is the office's home screen: every app in one place, behind the sign-in. It is part of the base of every office (layer 2).
How to use it: [Getting to know the centre](/en/use/console).

## Every app at an address of its own

The centre opens each app inside itself, at the address `/a/<alias>/`, and every screen in the centre is `#/m/<app>`. An app that runs in a [linked office](/en/concepts/link) opens here as a tile, marked with the mark of its office.

## A link you give a person

A link sent to a person has one builder:

```bash
./bbox console link <ref>
```

- `<ref>` is a work item, a meeting, or an app in the office.
- The link is built in the herd's centre, and opened past the sign-in before it is given. If it does not open, the command gives no link, and says why.
- An internal address (`.localhost`, an IP address, a port) is not given: on a phone, `localhost` is the phone itself.

| Command | What it does |
|---|---|
| `./bbox console link list` | Every link given: to whom, when, and when it last opened |
| `./bbox console link check` | Opens every link given again, and fails if one of them no longer opens |

## How to check it works

- The centre's address (`CONSOLE_BASE_URL` in the `.env` file) opens after the sign-in, and shows the apps.
- `Ctrl K` opens search.

## Going further

- [Getting to know the centre](/en/use/console)
- [App Management](/en/apps/app-management)
- [Link](/en/concepts/link)
