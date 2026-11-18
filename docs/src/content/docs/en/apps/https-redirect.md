---
title: HTTPS redirect
description: "On a server office, port 80 answers 308 to https and serves no content — but only when this app is on. Onboarding turns it on on a server with a public address; without onboarding it is off."
---

## What it is

«HTTPS redirect» (`https-redirect`) is a server office's answer on port 80: a redirect (308) to the same address over https, and nothing else. It is part of the base (layer 2), and has no screen and no address of its own. The [edge router](/en/apps/traefik) asks it about every request that arrives over HTTP.

308 and not 301: a 301 redirect turns a POST request into a GET at the client, and a webhook set up with `http://` would arrive empty. 308 keeps the method and the body.

## When it is on

The redirect is written only when the office is a server office (a public domain and a certificate), **and this app is on**. In the default file it is off.

- **`./bbox onboarding` turns it on by itself** on a computer that has a public address on one of its interfaces (or when `BBOX_HOST_SERVER=1` is declared), together with [Security](/en/apps/security). On that computer it also hardens the server itself: SSH sign-in by key only, and a firewall that leaves only the office's doors open. It is not applied at all if root has no key that opens a shell. When it is applied, it reverts by itself after 10 minutes, unless it is confirmed from a new SSH sign-in. Restarting the computer within the 10 minutes cancels the revert.
- **It stays off** when onboarding is skipped (for example `./bbox run` straight after the install), or on a server whose public address is behind NAT. There every app also answers over HTTP, without encryption, until you turn it on by hand:

```bash
./bbox apps enable https-redirect
./bbox run
```

The apps screen does not turn on an app of the base, which is why this is on the command line.

## What it does not redirect

- **Certificate verifications** (`/.well-known/acme-challenge/`): the edge router answers them over HTTP. A redirect there would break every certificate renewal.
- **A local office** (`localhost`): it has no certificate. There port 80 is the office, and it must not be redirected.
- **An explicit off:** `HTTPS_REDIRECT=off` in `.env` leaves port 80 without a redirect even when the app is on.

## How to check it works

On a server, an app's address over HTTP should answer 308, never 200 with content:

```bash
curl -sI http://<app>.<domain>/
```

## Going further

- [Edge router](/en/apps/traefik)
- [Security](/en/apps/security)
- [The apps](/en/apps)
