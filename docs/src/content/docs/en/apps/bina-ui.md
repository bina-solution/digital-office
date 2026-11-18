---
title: UI library
description: "The parts every screen in the office shares: the one palette «Olive Grove», the side menu, tables, icons — and how a new app stays consistent with them."
---

## What it is

«UI library» (`bina-ui`) is the parts every screen in the office shares. It is part of the base of every office (layer 2), but it does not run: it has no container and no tile. Its copy is written into the code of every app that uses it, and kept there.

## What it holds

| Part | What it is |
|---|---|
| The «Olive Grove» palette (`theme-tokens.css`) | The office's colours, light and dark. The only source of colours: every screen carries a copy of it |
| The side menu (`bina-nav.js`) | An app declares its menu, and the part builds it, on a phone too |
| Tables (`bina-table.js`) | One table for every screen |
| Icons, the page frame, error messages and questions inside the page | The same look and the same words on every screen that carries them |

## A new app

An app must stay installable on its own, so it holds a copy of the parts and does not load them from here. Two checks keep the copies from drifting:

- **Every copy is identical to the source.** A copy that changed fails the check.
- **A screen writes no colour of its own.** It uses only names from the palette, such as `var(--ink)` or `var(--accent)`. A colour written directly in a screen fails the check, except exceptions defined by name, such as the site's icon, a QR code or a provider's mark.

How to add the copy to a new screen: `ai/context/build-your-first-app.md`, in the chapter on the screen.

## Going further

- [The apps](/en/apps)
- [Console (the centre)](/en/apps/console)
- [App](/en/concepts/app)
